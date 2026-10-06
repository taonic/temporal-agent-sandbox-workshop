"""Talk to Max from a terminal (the web app does the same things with buttons).

    uv run max ask "Which store grew fastest?"
    uv run max team "Q1" "Q2" "Q3"
    uv run max status <workflow-id>
    uv run max approve <workflow-id> | reject <workflow-id>
    uv run max new-data <workflow-id>
    uv run max dismiss <workflow-id>
"""

import argparse
import asyncio
import json

from max_agent.agent.models import Decision
from max_agent.agent.workflow import MaxWorkflow
from max_agent.client import connect, start_max, start_team
from max_agent.config import settings
from max_agent.datasets import append_day


async def main() -> None:
    p = argparse.ArgumentParser(prog="max")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ask").add_argument("question")
    sub.add_parser("team").add_argument("questions", nargs="+")
    for name in ("status", "approve", "reject", "new-data", "dismiss"):
        sub.add_parser(name).add_argument("workflow_id")
    args = p.parse_args()

    client = await connect()
    if args.cmd == "ask":
        handle = await start_max(client, args.question)
        print(f"Max is on it: {handle.id}\n  {settings.temporal_ui_url}/namespaces/{settings.temporal_namespace}/workflows/{handle.id}")
        return
    if args.cmd == "team":
        handle = await start_team(client, args.questions)
        print(f"Team started: {handle.id}")
        return

    handle = client.get_workflow_handle(args.workflow_id)
    if args.cmd == "status":
        status = await handle.query(MaxWorkflow.status)
        print(json.dumps(status.model_dump(mode="json", exclude={"steps"}), indent=2))
        for s in status.steps:
            print(f"  {s.n:>2}. [{s.kind}] {s.summary}")
    elif args.cmd in ("approve", "reject"):
        decision = Decision(approve=args.cmd == "approve", by="cli")
        print(await handle.execute_update("approve_publish", decision, result_type=str))
    elif args.cmd == "new-data":
        day = append_day()
        await handle.signal(MaxWorkflow.new_data)
        print(f"Added sales for {day}; Max will rerun.")
    elif args.cmd == "dismiss":
        await handle.signal(MaxWorkflow.dismiss)
        print("Max is retiring; its sandbox will be deleted.")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
