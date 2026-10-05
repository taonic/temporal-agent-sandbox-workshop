"""Local provider: a directory plus subprocesses.

Not a security boundary! It exists so tests and challenge checks can exercise
the Temporal logic without a Daytona account, and to prove the provider
interface is real. Learners use Daytona.
"""

import asyncio
import os
import shutil
import sys
from pathlib import Path

from max_agent.config import settings
from max_agent.sandbox.models import ExecRequest, ExecResult, SandboxSpec
from max_agent.sandbox.providers.base import PermanentProviderError, SandboxProvider


class LocalProvider(SandboxProvider):
    @property
    def root(self) -> Path:
        return Path(self.options.get("root", settings.artifacts_dir / ".local-sandboxes"))

    def _dir(self, sandbox_id: str) -> Path:
        d = self.root / sandbox_id
        if not d.exists():
            raise PermanentProviderError(f"sandbox {sandbox_id} not found")
        return d

    def _require_running(self, sandbox_id: str) -> Path:
        d = self._dir(sandbox_id)
        if (d / ".suspended").exists():
            raise PermanentProviderError(f"sandbox {sandbox_id} is suspended")
        return d

    async def create(self, spec: SandboxSpec) -> str:
        work = self.root / spec.name / "work"
        work.mkdir(parents=True, exist_ok=True)  # idempotent by construction
        return spec.name

    async def suspend(self, sandbox_id: str) -> None:
        (self._dir(sandbox_id) / ".suspended").touch()

    async def resume(self, sandbox_id: str) -> None:
        (self._dir(sandbox_id) / ".suspended").unlink(missing_ok=True)

    async def destroy(self, sandbox_id: str) -> None:
        shutil.rmtree(self.root / sandbox_id, ignore_errors=True)

    async def exec(self, sandbox_id: str, request: ExecRequest) -> ExecResult:
        work = self._require_running(sandbox_id) / "work"
        for path, content in request.files.items():
            target = work / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        # Put this interpreter first on PATH so `python` has pandas/matplotlib.
        env = {**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}", "MPLBACKEND": "Agg"}
        proc = await asyncio.create_subprocess_shell(
            request.command,
            cwd=work,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=request.timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            return ExecResult(exit_code=124, output=f"timed out after {request.timeout_s}s")
        return ExecResult(exit_code=proc.returncode or 0, output=out.decode(errors="replace"))

    async def upload(self, sandbox_id: str, content: bytes, remote_path: str) -> None:
        target = self._require_running(sandbox_id) / "work" / remote_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    async def download(self, sandbox_id: str, remote_path: str) -> bytes:
        target = self._require_running(sandbox_id) / "work" / remote_path
        if not target.exists():
            raise PermanentProviderError(f"{remote_path} not found in sandbox")
        return target.read_bytes()
