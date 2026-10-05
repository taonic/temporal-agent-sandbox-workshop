import asyncio
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
import pytest_asyncio
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment

from max_agent.config import Settings
from max_agent.datasets import write_working_copy
from max_agent.worker import build_worker


@pytest_asyncio.fixture(scope="session")
async def env():
    async with await WorkflowEnvironment.start_local(data_converter=pydantic_data_converter) as env:
        yield env


@pytest.fixture
def settings(tmp_path: Path, monkeypatch) -> Settings:
    data = tmp_path / "data"
    artifacts = tmp_path / "artifacts"
    # Activities read artifacts_dir from the global settings (channel file, local sandboxes).
    import max_agent.config as config

    s = replace(
        config.settings,
        task_queue=f"test-{uuid.uuid4().hex[:8]}",
        llm_mode="scripted",
        sandbox_provider="local",
        learner_id="test",
        idle_timeout_s=2,
        approval_timeout_s=3,
        data_dir=data,
        artifacts_dir=artifacts,
    )
    monkeypatch.setattr(config, "settings", s)
    write_working_copy(s, days=14)
    import max_agent.agent.activities as agent_activities
    import max_agent.sandbox.providers.local as local

    monkeypatch.setattr(agent_activities, "settings", s)
    monkeypatch.setattr(local, "settings", s)
    return s


@pytest_asyncio.fixture
async def worker(env, settings):
    async with build_worker(env.client, settings.task_queue):
        yield env.client


async def eventually(check, timeout: float = 30, every: float = 0.2):
    """Poll an async check until it returns truthy."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        result = await check()
        if result:
            return result
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting; last value {result!r}")
        await asyncio.sleep(every)


async def start_sandbox(client, settings, idle_timeout_s=2):
    """Start a SandboxWorkflow directly (no Max) on the local provider."""
    from max_agent.sandbox.models import ProviderConfig, SandboxInit, SandboxSpec
    from max_agent.sandbox.workflow import SandboxWorkflow

    name = f"sbx-{uuid.uuid4().hex[:8]}"
    handle = await client.start_workflow(SandboxWorkflow.run, None, id=name, task_queue=settings.task_queue)
    root = str(settings.artifacts_dir / ".local-sandboxes")
    await handle.execute_update(
        SandboxWorkflow.init,
        SandboxInit(
            provider=ProviderConfig(type="local", options={"root": root}),
            spec=SandboxSpec(name=name),
            idle_timeout_s=idle_timeout_s,
        ),
    )
    return handle, settings.artifacts_dir / ".local-sandboxes" / name


def phase_is(handle, *phases):
    from max_agent.agent.workflow import MaxWorkflow

    async def check():
        try:
            status = await handle.query(MaxWorkflow.status)
        except Exception:
            return None
        return status if status.phase in phases else None

    return check
