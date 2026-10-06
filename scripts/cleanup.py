"""Clean up after a learner (or a whole session).

1. Cancel the learner's running Max / team workflows. That's the polite path:
   each sandbox workflow deletes its own sandbox.
2. Sweep Daytona for anything still labeled app=max (and learner=...), as a
   backstop for sandboxes whose workflows are gone (e.g. a wiped dev server).

    uv run python scripts/cleanup.py                 # this learner (LEARNER_ID)
    uv run python scripts/cleanup.py --all-learners  # everyone on this Daytona org
    uv run python scripts/cleanup.py --dry-run
"""

import argparse
import asyncio

from max_agent.config import settings


async def cancel_workflows(dry_run: bool) -> None:
    from max_agent.client import connect

    try:
        client = await connect()
    except Exception as e:
        print(f"Temporal not reachable ({e}); skipping workflow cancellation")
        return
    query = (
        "ExecutionStatus = 'Running' AND WorkflowType IN ('MaxWorkflow', 'TeamWorkflow') "
        f"AND (WorkflowId STARTS_WITH 'max-{settings.learner_id}-' OR WorkflowId STARTS_WITH 'team-{settings.learner_id}-')"
    )
    async for wf in client.list_workflows(query):
        print(f"{'would cancel' if dry_run else 'cancelling'} {wf.id}")
        if not dry_run:
            await client.get_workflow_handle(wf.id).cancel()
    if not dry_run:
        await asyncio.sleep(15)  # give sandbox workflows a moment to delete their sandboxes


async def owner_running(workflow_id: str | None) -> bool | None:
    """Is the Max that owns this sandbox still running? None if we can't tell."""
    if not workflow_id:
        return None
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.service import RPCError, RPCStatusCode

    from max_agent.client import connect

    try:
        desc = await (await connect()).get_workflow_handle(workflow_id).describe()
        return desc.status == WorkflowExecutionStatus.RUNNING
    except RPCError as e:
        return False if e.status == RPCStatusCode.NOT_FOUND else None
    except Exception:
        return None


async def sweep_daytona(all_learners: bool, dry_run: bool) -> None:
    from daytona import AsyncDaytona, ListSandboxesQuery

    labels = {"app": "max"} if all_learners else {"app": "max", "learner": settings.learner_id}
    async with AsyncDaytona() as daytona:
        found = [s async for s in daytona.list(ListSandboxesQuery(labels=labels))]
        for s in found:
            running = await owner_running(s.labels.get("workflow"))
            owner = {True: "owned by a running workflow", False: "orphaned: its workflow has ended", None: "owner unknown"}[running]
            state = getattr(s.state, "value", s.state)
            print(f"{'  ' if dry_run else 'deleting '}{s.name}  [{state}]  learner={s.labels.get('learner')}  {owner}")
            if not dry_run:
                await s.delete(timeout=120)
        print(f"{len(found)} sandbox(es) {'on Daytona' if dry_run else 'deleted'}")


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--all-learners", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    # Only delete sandboxes, without first cancelling workflows (which needs a worker).
    p.add_argument("--sandboxes-only", action="store_true")
    args = p.parse_args()
    if not args.all_learners and not args.sandboxes_only:
        await cancel_workflows(args.dry_run)
    if settings.sandbox_provider == "daytona":
        await sweep_daytona(args.all_learners, args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
