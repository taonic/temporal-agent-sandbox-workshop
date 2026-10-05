"""SandboxWorkflow: one long-lived workflow per sandbox.

The workflow *is* the sandbox's source of truth. Its ID is the sandbox's
address, its state (running / suspended / ...) is what the `state` query
returns, and every operation goes through it as an Update. That gives us:

- Lifecycle guards: validators reject a request that makes no sense right
  now (exec before init, resume when not suspended) before it hits history.
- Auto-resume: an exec that arrives while suspended wakes the sandbox first.
- Idle auto-suspend: no traffic for `idle_timeout_s` and the sandbox is
  stopped, so you stop paying for it. Its files survive.
- Guaranteed cleanup: stop signal, cancellation or the parent going away all
  end in `destroy_sandbox`.

Ported from the Go sandbox-orchestration-harness, simplified for teaching.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from max_agent.sandbox.activities import (
        create_sandbox,
        destroy_sandbox,
        download_files,
        exec_in_sandbox,
        resume_sandbox,
        suspend_sandbox,
        upload_files,
    )
    from max_agent.sandbox.models import (
        CreateCall,
        ExecCall,
        ExecRequest,
        ExecResult,
        FileTransfer,
        Lifecycle,
        ProviderCall,
        SandboxInit,
        SandboxState,
        SandboxStatus,
        TransferCall,
    )
    from max_agent.sandbox.providers import is_registered

LIFECYCLE_TIMEOUT = timedelta(minutes=3)
TRANSFER_TIMEOUT = timedelta(minutes=2)
# Keep history small: hand off to a fresh run after this many operations.
CONTINUE_AS_NEW_AFTER = 200


@workflow.defn
class SandboxWorkflow:
    @workflow.init
    def __init__(self, state: SandboxState | None = None) -> None:
        self._s = state or SandboxState()
        self._stop_requested = False
        self._busy = 0  # operations in flight
        self._activity_seq = 0  # bumps after every exec/upload/download
        self._ops_this_run = 0
        # One operation at a time: exec, suspend and resume never interleave.
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ run

    @workflow.run
    async def run(self, state: SandboxState | None = None) -> SandboxStatus:
        # A brand-new sandbox waits for its `init` update; a continued-as-new
        # run already has its state.
        await workflow.wait_condition(lambda: self._s.lifecycle != Lifecycle.PENDING or self._stop_requested)
        if self._s.lifecycle == Lifecycle.FAILED:
            return self.state()

        try:
            while not self._stop_requested:
                if self._should_continue_as_new():
                    # Let in-flight handlers finish, then carry state into a fresh history.
                    await workflow.wait_condition(lambda: workflow.all_handlers_finished() and self._busy == 0)
                    workflow.continue_as_new(self._s)
                await self._watch_for_idle()
            # Graceful stop: finish what's running, then clean up.
            await workflow.wait_condition(lambda: self._busy == 0)
            await self._destroy()
        except asyncio.CancelledError:
            # The owner was cancelled (or went away). Still clean up, then report cancelled.
            await self._destroy()
            raise
        return self.state()

    async def _watch_for_idle(self) -> None:
        """Suspend the sandbox once nothing has used it for `idle_timeout_s`."""
        # Sleep until there's something to watch: a running sandbox nobody is using.
        await workflow.wait_condition(
            lambda: self._stop_requested
            or self._should_continue_as_new()
            or (self._s.lifecycle == Lifecycle.RUNNING and self._busy == 0 and self._idle_enabled())
        )
        if self._stop_requested or self._should_continue_as_new():
            return

        seen = self._activity_seq

        def used_again() -> bool:
            return self._stop_requested or self._should_continue_as_new() or self._busy > 0 or self._activity_seq != seen

        try:
            # A durable timer: survives worker restarts, costs nothing while waiting.
            await workflow.wait_condition(used_again, timeout=timedelta(seconds=self._s.init.idle_timeout_s))
        except asyncio.TimeoutError:
            workflow.logger.info("sandbox idle for %ss, suspending", self._s.init.idle_timeout_s)
            async with self._lock:
                if self._s.lifecycle == Lifecycle.RUNNING:
                    await self._suspend()

    # -------------------------------------------------------------- handlers

    @workflow.query
    def state(self) -> SandboxStatus:
        init = self._s.init
        return SandboxStatus(
            lifecycle=self._s.lifecycle,
            sandbox_id=self._s.sandbox_id,
            provider=init.provider.type if init else None,
            commands_run=self._s.commands_run,
            suspend_count=self._s.suspend_count,
            resume_count=self._s.resume_count,
            idle_timeout_s=init.idle_timeout_s if init else None,
            busy=self._busy > 0,
        )

    @workflow.signal
    def stop(self) -> None:
        self._stop_requested = True

    @workflow.update
    async def init(self, init: SandboxInit) -> SandboxStatus:
        self._s.init = init
        self._s.lifecycle = Lifecycle.CREATING
        try:
            self._s.sandbox_id = await workflow.execute_activity(
                create_sandbox,
                CreateCall(provider=init.provider, spec=init.spec),
                start_to_close_timeout=LIFECYCLE_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
        except Exception:
            self._s.lifecycle = Lifecycle.FAILED
            raise
        self._s.lifecycle = Lifecycle.RUNNING
        return self.state()

    @init.validator
    def validate_init(self, init: SandboxInit) -> None:
        if self._s.lifecycle != Lifecycle.PENDING:
            raise ApplicationError("sandbox already initialized", type="AlreadyInitialized")
        if not is_registered(init.provider.type):
            raise ApplicationError(f"unknown provider {init.provider.type!r}", type="InvalidArgument")

    @workflow.update
    async def exec(self, request: ExecRequest) -> ExecResult:
        return await self._use(
            lambda: workflow.execute_activity(
                exec_in_sandbox,
                ExecCall(provider=self._s.init.provider, sandbox_id=self._s.sandbox_id, request=request),
                start_to_close_timeout=timedelta(seconds=request.timeout_s + 60),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        )

    @exec.validator
    def validate_exec(self, request: ExecRequest) -> None:
        self._require_usable()

    @workflow.update
    async def upload(self, transfers: list[FileTransfer]) -> None:
        await self._use(
            lambda: workflow.execute_activity(
                upload_files, self._transfer_call(transfers), start_to_close_timeout=TRANSFER_TIMEOUT
            )
        )

    @upload.validator
    def validate_upload(self, transfers: list[FileTransfer]) -> None:
        self._require_usable()

    @workflow.update
    async def download(self, transfers: list[FileTransfer]) -> list[str]:
        return await self._use(
            lambda: workflow.execute_activity(
                download_files, self._transfer_call(transfers), start_to_close_timeout=TRANSFER_TIMEOUT
            )
        )

    @download.validator
    def validate_download(self, transfers: list[FileTransfer]) -> None:
        self._require_usable()

    @workflow.update
    async def suspend(self) -> SandboxStatus:
        async with self._lock:
            if self._s.lifecycle == Lifecycle.RUNNING:
                await self._suspend()
        return self.state()

    @suspend.validator
    def validate_suspend(self) -> None:
        self._require_usable()
        if self._s.lifecycle == Lifecycle.SUSPENDED:
            raise ApplicationError("sandbox already suspended", type="AlreadySuspended")

    @workflow.update
    async def resume(self) -> SandboxStatus:
        async with self._lock:
            if self._s.lifecycle == Lifecycle.SUSPENDED:
                await self._resume()
        return self.state()

    @resume.validator
    def validate_resume(self) -> None:
        self._require_usable()
        if self._s.lifecycle != Lifecycle.SUSPENDED:
            raise ApplicationError("sandbox is not suspended", type="NotSuspended")

    # --------------------------------------------------------------- helpers

    async def _use(self, operation):
        """Run one operation against the sandbox, waking it first if it's asleep."""
        self._busy += 1
        try:
            async with self._lock:
                if self._s.lifecycle == Lifecycle.SUSPENDED:
                    await self._resume()  # auto-resume
                result = await operation()
                self._s.commands_run += 1
                return result
        finally:
            self._activity_seq += 1
            self._ops_this_run += 1
            self._busy -= 1

    async def _suspend(self) -> None:
        self._s.lifecycle = Lifecycle.SUSPENDING
        try:
            await workflow.execute_activity(
                suspend_sandbox, self._provider_call(), start_to_close_timeout=LIFECYCLE_TIMEOUT
            )
        except Exception:
            self._s.lifecycle = Lifecycle.RUNNING
            raise
        self._s.lifecycle = Lifecycle.SUSPENDED
        self._s.suspend_count += 1

    async def _resume(self) -> None:
        self._s.lifecycle = Lifecycle.RESUMING
        try:
            await workflow.execute_activity(
                resume_sandbox, self._provider_call(), start_to_close_timeout=LIFECYCLE_TIMEOUT
            )
        except Exception:
            self._s.lifecycle = Lifecycle.SUSPENDED
            raise
        self._s.lifecycle = Lifecycle.RUNNING
        self._s.resume_count += 1

    async def _destroy(self) -> None:
        if self._s.sandbox_id is None or self._s.lifecycle == Lifecycle.DELETED:
            return
        self._s.lifecycle = Lifecycle.STOPPING
        await workflow.execute_activity(
            destroy_sandbox,
            self._provider_call(),
            start_to_close_timeout=LIFECYCLE_TIMEOUT,
            retry_policy=RetryPolicy(maximum_interval=timedelta(seconds=30)),  # keep trying: leaks cost money
        )
        self._s.lifecycle = Lifecycle.DELETED

    def _require_usable(self) -> None:
        if self._s.lifecycle in (Lifecycle.PENDING, Lifecycle.CREATING, Lifecycle.FAILED):
            raise ApplicationError("sandbox not initialized", type="NotInitialized")
        if self._stop_requested or self._s.lifecycle in (Lifecycle.STOPPING, Lifecycle.DELETED):
            raise ApplicationError("sandbox is shutting down", type="ShuttingDown")

    def _idle_enabled(self) -> bool:
        return self._s.init is not None and self._s.init.idle_timeout_s > 0

    def _should_continue_as_new(self) -> bool:
        return self._ops_this_run >= CONTINUE_AS_NEW_AFTER or workflow.info().is_continue_as_new_suggested()

    def _provider_call(self) -> ProviderCall:
        return ProviderCall(provider=self._s.init.provider, sandbox_id=self._s.sandbox_id)

    def _transfer_call(self, transfers: list[FileTransfer]) -> TransferCall:
        return TransferCall(provider=self._s.init.provider, sandbox_id=self._s.sandbox_id, transfers=transfers)
