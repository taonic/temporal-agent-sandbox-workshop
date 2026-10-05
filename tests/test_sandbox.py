"""The provided sandbox workflow: lifecycle guards and cleanup (no TODOs here)."""

import pytest
from temporalio.client import WorkflowUpdateFailedError

from max_agent.sandbox.models import ProviderConfig, SandboxInit, SandboxSpec
from max_agent.sandbox.workflow import SandboxWorkflow

from .conftest import eventually, start_sandbox


async def test_validators_reject_nonsense(worker, settings):
    handle, _ = await start_sandbox(worker, settings, idle_timeout_s=0)
    with pytest.raises(WorkflowUpdateFailedError) as e:
        await handle.execute_update(SandboxWorkflow.resume)
    assert "not suspended" in str(e.value.cause)
    with pytest.raises(WorkflowUpdateFailedError) as e:
        await handle.execute_update(
            SandboxWorkflow.init, SandboxInit(provider=ProviderConfig(type="local"), spec=SandboxSpec(name="x"))
        )
    assert "already initialized" in str(e.value.cause)
    await handle.cancel()


async def test_cancel_cleans_up(worker, settings):
    handle, path = await start_sandbox(worker, settings, idle_timeout_s=0)
    assert path.exists()
    await handle.cancel()
    await eventually(lambda: _async(not path.exists()))


async def _async(v):
    return v
