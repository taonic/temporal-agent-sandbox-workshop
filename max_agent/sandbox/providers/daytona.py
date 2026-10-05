"""Daytona provider.

Notes on mapping Daytona onto our lifecycle:
- suspend/resume = Daytona stop/start (the filesystem survives a stop).
- Daytona's own auto-stop is disabled (auto_stop_interval=0): the sandbox
  workflow decides when Max is idle, because Daytona only counts API calls as
  activity. auto_delete_interval is a cost backstop if everything else fails.
- Create is idempotent via the sandbox name: a Conflict means a previous
  attempt already created it, so we look it up instead.
"""

from daytona import (
    AsyncDaytona,
    CreateSandboxFromSnapshotParams,
    DaytonaAuthenticationError,
    DaytonaConflictError,
    DaytonaError,
    DaytonaFileNotFoundError,
    DaytonaNotFoundError,
    SandboxState,
)

from max_agent.sandbox.models import ExecRequest, ExecResult, SandboxSpec
from max_agent.sandbox.providers.base import PermanentProviderError, SandboxProvider

_client: AsyncDaytona | None = None


def _daytona() -> AsyncDaytona:
    # One client per worker process; activities share it.
    global _client
    if _client is None:
        _client = AsyncDaytona()
    return _client


class DaytonaProvider(SandboxProvider):
    async def _get(self, sandbox_id: str):
        try:
            return await _daytona().get(sandbox_id)
        except DaytonaNotFoundError as e:
            raise PermanentProviderError(f"sandbox {sandbox_id} not found") from e
        except DaytonaAuthenticationError as e:
            raise PermanentProviderError("Daytona rejected the API key") from e

    async def create(self, spec: SandboxSpec) -> str:
        params = CreateSandboxFromSnapshotParams(
            name=spec.name,
            snapshot=self.options.get("snapshot") or None,
            labels=spec.labels,
            network_block_all=spec.network_blocked,
            auto_stop_interval=0,
            auto_delete_interval=int(self.options.get("auto_delete_minutes", "60")),
        )
        try:
            sandbox = await _daytona().create(params, timeout=120)
        except DaytonaConflictError:
            # Already created by an earlier attempt of this activity.
            sandbox = await _daytona().get(spec.name)
        except DaytonaAuthenticationError as e:
            raise PermanentProviderError("Daytona rejected the API key") from e
        if sandbox.state != SandboxState.STARTED:
            await sandbox.start(timeout=120)
        return sandbox.id

    async def suspend(self, sandbox_id: str) -> None:
        sandbox = await self._get(sandbox_id)
        if sandbox.state not in (SandboxState.STOPPED, SandboxState.STOPPING):
            await sandbox.stop(timeout=120)

    async def resume(self, sandbox_id: str) -> None:
        sandbox = await self._get(sandbox_id)
        if sandbox.state != SandboxState.STARTED:
            await sandbox.start(timeout=120)

    async def destroy(self, sandbox_id: str) -> None:
        try:
            sandbox = await _daytona().get(sandbox_id)
            await sandbox.delete(timeout=120)
        except DaytonaNotFoundError:
            pass

    async def exec(self, sandbox_id: str, request: ExecRequest) -> ExecResult:
        sandbox = await self._get(sandbox_id)
        for path, content in request.files.items():
            await sandbox.fs.upload_file(content.encode(), path)
        resp = await sandbox.process.exec(request.command, timeout=request.timeout_s)
        return ExecResult(exit_code=resp.exit_code, output=resp.result or "")

    async def upload(self, sandbox_id: str, content: bytes, remote_path: str) -> None:
        sandbox = await self._get(sandbox_id)
        await sandbox.fs.upload_file(content, remote_path)

    async def download(self, sandbox_id: str, remote_path: str) -> bytes:
        sandbox = await self._get(sandbox_id)
        try:
            data = await sandbox.fs.download_file(remote_path)
        except (DaytonaFileNotFoundError, DaytonaNotFoundError) as e:
            raise PermanentProviderError(f"{remote_path} not found in sandbox") from e
        except DaytonaError as e:
            # Some SDK versions report a missing file as a generic error.
            if "not found" in str(e).lower():
                raise PermanentProviderError(f"{remote_path} not found in sandbox") from e
            raise
        if data is None:
            raise PermanentProviderError(f"{remote_path} not found in sandbox")
        return data
