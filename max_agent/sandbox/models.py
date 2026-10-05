"""Payload types shared by the sandbox workflow, its activities and its callers."""

from enum import Enum

from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    """Which compute provider to use and its provider-specific options."""

    type: str  # "daytona" | "local"
    options: dict[str, str] = Field(default_factory=dict)


class SandboxSpec(BaseModel):
    # Deterministic name (derived from the workflow ID). Providers use it to make
    # create idempotent: a retried create finds the sandbox instead of leaking a twin.
    name: str
    labels: dict[str, str] = Field(default_factory=dict)
    network_blocked: bool = True


class Lifecycle(str, Enum):
    PENDING = "pending"  # waiting for the init update
    CREATING = "creating"
    RUNNING = "running"
    SUSPENDING = "suspending"
    SUSPENDED = "suspended"
    RESUMING = "resuming"
    STOPPING = "stopping"
    DELETED = "deleted"
    FAILED = "failed"


class ExecRequest(BaseModel):
    command: str
    # Text files (path relative to the sandbox work dir -> content) written
    # before the command runs. Handy for "write this script, then run it".
    files: dict[str, str] = Field(default_factory=dict)
    timeout_s: int = 120


class ExecResult(BaseModel):
    exit_code: int
    # stdout and stderr interleaved. Daytona's exec API only returns combined output.
    output: str


class FileTransfer(BaseModel):
    remote_path: str  # relative to the sandbox work dir
    local_path: str  # on the worker's machine


class SandboxInit(BaseModel):
    provider: ProviderConfig
    spec: SandboxSpec
    idle_timeout_s: int = 60  # <= 0 disables idle auto-suspend


class SandboxState(BaseModel):
    """Everything the sandbox workflow carries across continue-as-new."""

    init: SandboxInit | None = None
    sandbox_id: str | None = None
    lifecycle: Lifecycle = Lifecycle.PENDING
    commands_run: int = 0
    suspend_count: int = 0
    resume_count: int = 0


class SandboxStatus(BaseModel):
    """What the `state` query returns."""

    lifecycle: Lifecycle
    sandbox_id: str | None
    provider: str | None
    commands_run: int
    suspend_count: int
    resume_count: int
    idle_timeout_s: int | None
    busy: bool


# --- activity inputs -------------------------------------------------------

class ProviderCall(BaseModel):
    provider: ProviderConfig
    sandbox_id: str


class ExecCall(ProviderCall):
    request: ExecRequest


class TransferCall(ProviderCall):
    transfers: list[FileTransfer]


class CreateCall(BaseModel):
    provider: ProviderConfig
    spec: SandboxSpec


class SandboxUpdateCall(BaseModel):
    """Input to the activity that forwards a request to a sandbox workflow."""

    sandbox_workflow_id: str
    update: str  # update handler name
    update_id: str  # stable across activity retries -> the update runs at most once
    arg: dict | list | None = None
