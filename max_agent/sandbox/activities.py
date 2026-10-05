"""Activities. Everything that touches the outside world lives here.

Two groups:
- Provider activities: called *by* SandboxWorkflow to create/exec/suspend/...
- `call_sandbox`: called by other workflows (e.g. Max) to send an Update *to*
  a SandboxWorkflow. Workflow code can signal another workflow but can't send
  it an Update, so we hop through an activity using the Temporal client.
"""

import functools
from pathlib import Path
from typing import Any

from temporalio import activity
from temporalio.client import Client, WorkflowUpdateFailedError
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError, RPCStatusCode

from max_agent.sandbox.models import CreateCall, ExecCall, ExecResult, ProviderCall, SandboxUpdateCall, TransferCall
from max_agent.sandbox.providers import PermanentProviderError, get_provider


def _permanent_errors_are_non_retryable(fn):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except PermanentProviderError as e:
            raise ApplicationError(str(e), type="PermanentProviderError", non_retryable=True) from e

    return wrapper


@activity.defn
@_permanent_errors_are_non_retryable
async def create_sandbox(call: CreateCall) -> str:
    sandbox_id = await get_provider(call.provider).create(call.spec)
    activity.logger.info("sandbox ready: %s (%s)", call.spec.name, sandbox_id)
    return sandbox_id


@activity.defn
@_permanent_errors_are_non_retryable
async def suspend_sandbox(call: ProviderCall) -> None:
    await get_provider(call.provider).suspend(call.sandbox_id)


@activity.defn
@_permanent_errors_are_non_retryable
async def resume_sandbox(call: ProviderCall) -> None:
    await get_provider(call.provider).resume(call.sandbox_id)


@activity.defn
@_permanent_errors_are_non_retryable
async def destroy_sandbox(call: ProviderCall) -> None:
    await get_provider(call.provider).destroy(call.sandbox_id)


@activity.defn
@_permanent_errors_are_non_retryable
async def exec_in_sandbox(call: ExecCall) -> ExecResult:
    return await get_provider(call.provider).exec(call.sandbox_id, call.request)


@activity.defn
@_permanent_errors_are_non_retryable
async def upload_files(call: TransferCall) -> None:
    provider = get_provider(call.provider)
    for t in call.transfers:
        await provider.upload(call.sandbox_id, Path(t.local_path).read_bytes(), t.remote_path)


@activity.defn
@_permanent_errors_are_non_retryable
async def download_files(call: TransferCall) -> list[str]:
    """Copy files out of the sandbox onto this machine. Missing files are skipped.

    Only the local paths go back into workflow history, never the bytes.
    """
    provider = get_provider(call.provider)
    saved = []
    for t in call.transfers:
        try:
            data = await provider.download(call.sandbox_id, t.remote_path)
        except PermanentProviderError:
            continue
        Path(t.local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(t.local_path).write_bytes(data)
        saved.append(t.local_path)
    return saved


SANDBOX_ACTIVITIES = [create_sandbox, suspend_sandbox, resume_sandbox, destroy_sandbox, exec_in_sandbox, upload_files, download_files]


class SandboxCaller:
    def __init__(self, client: Client):
        self.client = client

    @activity.defn
    async def call_sandbox(self, call: SandboxUpdateCall) -> Any:
        handle = self.client.get_workflow_handle(call.sandbox_workflow_id)
        try:
            # A retried attempt reuses update_id, so Temporal dedupes it and hands
            # back the original outcome instead of running the command twice.
            return await handle.execute_update(call.update, call.arg, id=call.update_id)
        except WorkflowUpdateFailedError as e:
            cause = e.cause
            if isinstance(cause, ApplicationError):
                # Rejected by a validator or failed in the handler: surface it to the
                # caller as-is. Retrying the same request won't change the answer.
                raise ApplicationError(cause.message, *cause.details, type=cause.type, non_retryable=True) from e
            raise
        except RPCError as e:
            if e.status == RPCStatusCode.NOT_FOUND:
                raise ApplicationError(f"sandbox workflow {call.sandbox_workflow_id} is gone", type="SandboxGone", non_retryable=True) from e
            raise
