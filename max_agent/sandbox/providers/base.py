"""The provider interface: the only code that knows how a sandbox is really made."""

from abc import ABC, abstractmethod

from max_agent.sandbox.models import ExecRequest, ExecResult, SandboxSpec


class PermanentProviderError(Exception):
    """An error retrying won't fix (bad credentials, sandbox gone, invalid input)."""


class SandboxProvider(ABC):
    def __init__(self, options: dict[str, str]):
        self.options = options

    @abstractmethod
    async def create(self, spec: SandboxSpec) -> str:
        """Create a sandbox and return its ID. Must be idempotent on spec.name."""

    @abstractmethod
    async def suspend(self, sandbox_id: str) -> None:
        """Stop paying for compute but keep the filesystem. Idempotent."""

    @abstractmethod
    async def resume(self, sandbox_id: str) -> None:
        """Bring a suspended sandbox back. Idempotent."""

    @abstractmethod
    async def destroy(self, sandbox_id: str) -> None:
        """Delete the sandbox. Idempotent: an already-deleted sandbox is success."""

    @abstractmethod
    async def exec(self, sandbox_id: str, request: ExecRequest) -> ExecResult:
        """Write request.files, then run request.command in the work dir."""

    @abstractmethod
    async def upload(self, sandbox_id: str, content: bytes, remote_path: str) -> None: ...

    @abstractmethod
    async def download(self, sandbox_id: str, remote_path: str) -> bytes: ...
