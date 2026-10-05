"""The worker: runs Max's workflows and activities. Kill it any time; restart it and Max carries on."""

import asyncio
import logging
import re
from pathlib import Path

from temporalio.worker import Worker

from max_agent.agent.activities import AGENT_ACTIVITIES
from max_agent.agent.llm import call_llm
from max_agent.agent.team import TeamWorkflow
from max_agent.agent.workflow import MaxWorkflow
from max_agent.client import connect
from max_agent.config import settings
from max_agent.sandbox.activities import SANDBOX_ACTIVITIES, SandboxCaller
from max_agent.sandbox.workflow import SandboxWorkflow

WORKFLOWS = [MaxWorkflow, TeamWorkflow, SandboxWorkflow]


def build_worker(client, task_queue: str = settings.task_queue) -> Worker:
    return Worker(
        client,
        task_queue=task_queue,
        workflows=WORKFLOWS,
        activities=[*SANDBOX_ACTIVITIES, SandboxCaller(client).call_sandbox, call_llm, *AGENT_ACTIVITIES],
    )


def open_todos() -> list[str]:
    """Challenge TODOs still open in this checkout, e.g. ["ch01", "ch03"]."""
    root = Path(__file__).parent
    found = set()
    for rel in ("agent/workflow.py", "agent/team.py", "sandbox/workflow.py"):
        found.update(re.findall(r"TODO\((ch\d\d)\)", (root / rel).read_text()))
    return sorted(found)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    client = await connect()
    print(f"Max's worker is up: task queue {settings.task_queue!r}, sandboxes on {settings.sandbox_provider}, "
          f"LLM {settings.llm_mode}:{settings.llm_model}")
    if todos := open_todos():
        print(f"Running workshop starter code: {', '.join(todos)} not done yet. Runs will pause at those TODOs.\n"
              "  To run the finished Max instead: uv run python scripts/switch.py solution")
    await build_worker(client).run()


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nWorker stopped. Max's runs are paused, not lost: start the worker again to continue.")


if __name__ == "__main__":
    run()
