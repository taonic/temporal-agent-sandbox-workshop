"""Challenge 2: an idle sandbox suspends itself, and wakes up when it's needed."""

from max_agent.sandbox.models import ExecRequest, Lifecycle
from max_agent.sandbox.workflow import SandboxWorkflow

from .conftest import eventually, start_sandbox


async def test_idle_sandbox_suspends_then_auto_resumes(worker, settings):
    handle, path = await start_sandbox(worker, settings, idle_timeout_s=2)
    out = await handle.execute_update(SandboxWorkflow.exec, ExecRequest(command="echo hi > note.txt && cat note.txt"))
    assert out.exit_code == 0 and out.output.strip() == "hi"

    async def suspended():
        return (await handle.query(SandboxWorkflow.state)).lifecycle == Lifecycle.SUSPENDED

    try:
        await eventually(suspended, timeout=15)
    except AssertionError:
        raise AssertionError("The sandbox was idle for 2s but never suspended. Check _watch_for_idle's TODO.")

    # Using a suspended sandbox wakes it up, and its files are still there.
    out = await handle.execute_update(SandboxWorkflow.exec, ExecRequest(command="cat note.txt"))
    assert out.output.strip() == "hi"
    state = await handle.query(SandboxWorkflow.state)
    assert state.resume_count == 1 and state.suspend_count >= 1

    await handle.signal(SandboxWorkflow.stop)
    assert (await handle.result()).lifecycle == Lifecycle.DELETED
    assert not path.exists()


async def test_busy_sandbox_does_not_suspend(worker, settings):
    handle, _ = await start_sandbox(worker, settings, idle_timeout_s=2)
    out = await handle.execute_update(SandboxWorkflow.exec, ExecRequest(command="sleep 4 && echo done", timeout_s=30))
    assert out.output.strip() == "done"
    assert (await handle.query(SandboxWorkflow.state)).suspend_count == 0, "suspended while a command was running"
    await handle.signal(SandboxWorkflow.stop)
