"""Challenge 4: a team of Maxes works side by side, and cancelling the team cleans up everything."""

import asyncio

from temporalio.client import WorkflowExecutionStatus

from max_agent.agent.models import Phase
from max_agent.agent.team import TeamWorkflow
from max_agent.agent.workflow import MaxWorkflow
from max_agent.client import start_team

from .conftest import eventually


async def test_team_members_run_in_parallel(worker, settings):
    handle = await start_team(worker, ["Q one?", "Q two?", "Q three?"], settings)
    result = await asyncio.wait_for(handle.result(), timeout=60)
    assert len(result.members) == 3 and not result.failed
    assert open(result.report_path).read().count("Top store") == 3

    descs = [await worker.get_workflow_handle(i).describe() for i in await handle.query(TeamWorkflow.member_ids)]
    assert max(d.start_time for d in descs) < min(d.close_time for d in descs), (
        "Members ran one after another. Start them all first, then wait for them together."
    )


async def test_cancelling_the_team_deletes_every_sandbox(worker, settings):
    handle = await start_team(worker, ["Q one?", "Q two?"], settings)
    member_ids = await handle.query(TeamWorkflow.member_ids)

    async def first_member_has_sandbox():
        try:
            s = await worker.get_workflow_handle(member_ids[0]).query(MaxWorkflow.status)
            return s.sandbox_workflow_id and s.phase == Phase.ANALYZING
        except Exception:
            return False

    await eventually(first_member_has_sandbox)
    await handle.cancel()

    async def everything_closed():
        for i in member_ids:
            for wf in (i, f"sandbox-{i}"):
                try:
                    if (await worker.get_workflow_handle(wf).describe()).status == WorkflowExecutionStatus.RUNNING:
                        return False
                except Exception:
                    pass  # never started: nothing to clean up
        return True

    await eventually(everything_closed)
    root = settings.artifacts_dir / ".local-sandboxes"
    assert not root.exists() or not any(root.iterdir()), "a sandbox was left behind"
