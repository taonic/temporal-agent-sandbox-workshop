"""Bonus: put Max on a schedule, like a Dot that reruns your analysis every morning.

    uv run python scripts/schedule.py create "How did yesterday compare with the day before?" --every 5m
    uv run python scripts/schedule.py trigger     # run it now
    uv run python scripts/schedule.py delete

A Temporal Schedule starts a fresh MaxWorkflow on every tick. Each run gets its
own sandbox, asks for approval as usual, and retires shortly after.
"""

import argparse
import asyncio
from datetime import timedelta

from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from max_agent.agent.workflow import MaxWorkflow
from max_agent.client import analysis_input, connect
from max_agent.config import settings

SCHEDULE_ID = f"max-schedule-{settings.learner_id}"


def parse_every(text: str) -> timedelta:
    unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[text[-1]]
    return timedelta(**{unit: int(text[:-1])})


async def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    create = sub.add_parser("create")
    create.add_argument("question")
    create.add_argument("--every", default="5m")
    sub.add_parser("trigger")
    sub.add_parser("delete")
    args = p.parse_args()

    client = await connect()
    if args.cmd == "create":
        # A scheduled Max retires soon after its approval window instead of lingering.
        inp = analysis_input(args.question).model_copy(update={"linger_timeout_s": 60})
        await client.create_schedule(
            SCHEDULE_ID,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    MaxWorkflow.run,
                    inp,
                    # The schedule appends a timestamp to this ID on each run. It also
                    # names the sandbox, so it must start with max-<learner>- for cleanup.
                    id=f"max-{settings.learner_id}-sched",
                    task_queue=settings.task_queue,
                ),
                spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=parse_every(args.every))]),
                # Don't pile up Maxes if the last one is still waiting for approval.
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            ),
        )
        print(f"Schedule {SCHEDULE_ID} created: every {args.every}. See it under Schedules in the Temporal UI.")
    elif args.cmd == "trigger":
        await client.get_schedule_handle(SCHEDULE_ID).trigger()
        print("Triggered; a new Max is starting.")
    elif args.cmd == "delete":
        await client.get_schedule_handle(SCHEDULE_ID).delete()
        print("Schedule deleted.")


if __name__ == "__main__":
    asyncio.run(main())
