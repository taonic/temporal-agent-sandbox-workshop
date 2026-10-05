"""Workflow-side API for using a sandbox from any workflow.

    sandbox = await Sandbox.create(provider, spec, idle_timeout_s=60)
    result = await sandbox.exec("python analyze.py", files={"analyze.py": code})
    await sandbox.stop()

Under the hood: `create` starts a SandboxWorkflow as a child workflow, then
every call is an Update to it, sent through the `call_sandbox` activity.
Use it only from workflow code.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from max_agent.sandbox.activities import SandboxCaller
    from max_agent.sandbox.models import (
        ExecRequest,
        ExecResult,
        FileTransfer,
        ProviderConfig,
        SandboxInit,
        SandboxSpec,
        SandboxStatus,
        SandboxUpdateCall,
    )
    from max_agent.sandbox.workflow import SandboxWorkflow


class Sandbox:
    def __init__(self, workflow_id: str, child: workflow.ChildWorkflowHandle | None = None) -> None:
        self.workflow_id = workflow_id
        self._child = child

    @staticmethod
    async def create(provider: ProviderConfig, spec: SandboxSpec, idle_timeout_s: int = 60) -> "Sandbox":
        workflow_id = f"sandbox-{spec.name}"
        child = await workflow.start_child_workflow(
            SandboxWorkflow.run,
            None,
            id=workflow_id,
            # If our workflow is cancelled or ends, the sandbox workflow gets a
            # cancellation request and cleans up the real sandbox. (The default,
            # TERMINATE, would kill it before it could delete anything.)
            parent_close_policy=ParentClosePolicy.REQUEST_CANCEL,
            static_summary=f"sandbox {spec.name} ({provider.type})",
        )
        sandbox = Sandbox(workflow_id, child)
        await sandbox._update("init", SandboxInit(provider=provider, spec=spec, idle_timeout_s=idle_timeout_s))
        return sandbox

    async def exec(self, command: str, files: dict[str, str] | None = None, timeout_s: int = 120) -> ExecResult:
        req = ExecRequest(command=command, files=files or {}, timeout_s=timeout_s)
        # Allow time for an auto-resume on top of the command itself.
        out = await self._update("exec", req, timeout=timedelta(seconds=timeout_s + 300))
        return ExecResult.model_validate(out)

    async def upload(self, transfers: list[FileTransfer]) -> None:
        await self._update("upload", transfers)

    async def download(self, transfers: list[FileTransfer]) -> list[str]:
        return await self._update("download", transfers)

    async def suspend(self) -> SandboxStatus:
        return SandboxStatus.model_validate(await self._update("suspend", None))

    async def resume(self) -> SandboxStatus:
        return SandboxStatus.model_validate(await self._update("resume", None))

    async def stop(self) -> None:
        """Ask the sandbox workflow to delete the sandbox, and wait until it has."""
        await workflow.get_external_workflow_handle(self.workflow_id).signal(SandboxWorkflow.stop)
        if self._child is not None:
            await self._child

    async def _update(self, name: str, arg, timeout: timedelta = timedelta(minutes=5)):
        if isinstance(arg, list):
            arg = [a.model_dump() for a in arg]
        elif arg is not None:
            arg = arg.model_dump()
        return await workflow.execute_activity_method(
            SandboxCaller.call_sandbox,
            SandboxUpdateCall(
                sandbox_workflow_id=self.workflow_id,
                update=name,
                # Generated once and recorded in history, so every retry of this
                # activity sends the same update ID.
                update_id=str(workflow.uuid4()),
                arg=arg,
            ),
            start_to_close_timeout=timeout,
            retry_policy=RetryPolicy(maximum_attempts=5),
            summary=f"sandbox.{name}",
        )
