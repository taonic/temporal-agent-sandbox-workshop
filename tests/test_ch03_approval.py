"""Challenge 3: Max asks before posting, and gives up politely if nobody answers."""

import pytest
from temporalio.client import WorkflowUpdateFailedError

from max_agent.agent.activities import read_channel
from max_agent.agent.models import Decision, Phase
from max_agent.agent.workflow import MaxWorkflow
from max_agent.client import start_max

from .conftest import eventually, phase_is


async def test_approved_report_is_posted_once(worker, settings):
    handle = await start_max(worker, "Which store sells the most?", settings)
    await eventually(phase_is(handle, Phase.AWAITING_APPROVAL), timeout=30)
    assert read_channel() == [], "Max posted before anyone approved"

    await handle.execute_update("approve_publish", Decision(approve=True, by="tester"))
    status = await eventually(phase_is(handle, Phase.WAITING_FOR_DATA))
    assert status.published
    assert [p["workflow_id"] for p in read_channel()] == [handle.id]

    # The validator turns away a second click: Max isn't waiting any more.
    with pytest.raises(WorkflowUpdateFailedError):
        await handle.execute_update("approve_publish", Decision(approve=True, by="tester"))
    await handle.signal(MaxWorkflow.dismiss)
    await handle.result()


async def test_rejected_or_ignored_report_is_not_posted(worker, settings):
    handle = await start_max(worker, "Which store sells the most?", settings)
    await eventually(phase_is(handle, Phase.AWAITING_APPROVAL), timeout=30)
    await handle.execute_update("approve_publish", Decision(approve=False, by="tester"))
    await eventually(phase_is(handle, Phase.WAITING_FOR_DATA))

    await handle.signal(MaxWorkflow.new_data)
    await eventually(phase_is(handle, Phase.AWAITING_APPROVAL), timeout=30)
    # Nobody answers: after approval_timeout_s Max moves on without posting.
    status = await eventually(phase_is(handle, Phase.WAITING_FOR_DATA), timeout=settings.approval_timeout_s + 10)
    assert not status.published and read_channel() == []
    await handle.signal(MaxWorkflow.dismiss)
    await handle.result()
