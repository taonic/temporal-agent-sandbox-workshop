"""Benchmark the model + sandbox end to end: does Max actually finish?

Runs each question as a non-interactive Max (real model, real sandbox) and
reports steps, wall time and whether a report and chart were produced.
Needs a running worker. Use this on the Instruqt VM to choose a model size.

    uv run python scripts/bench_llm.py [--model qwen3.5:9b] [--runs 1] [--concurrency 2]
"""

import argparse
import asyncio
import time
from dataclasses import replace

from max_agent.agent.workflow import MaxWorkflow
from max_agent.client import analysis_input, connect, new_id
from max_agent.config import settings

# One question per kind of reasoning; datasets/coffee-chain/README.md has the expected answers.
QUESTIONS = [
    "Which store had the highest revenue in the last 7 days?",  # single table, recency
    "Does rainy weather change Cold Brew sales? By how much?",  # single table, comparison
    "Did Mission's Cold Brew promotion pay off?",  # sales + promotions
    "Is SoMa overstaffed at weekends?",  # sales + shifts
    "Why is Castro wasting so much oat milk?",  # inventory + sales
    "Is there anything wrong with the sales data?",  # data quality
]


async def run_one(client, question: str, s) -> dict:
    inp = analysis_input(question, s).model_copy(update={"interactive": False})
    t = time.monotonic()
    handle = await client.start_workflow(MaxWorkflow.run, inp, id=new_id("bench", s), task_queue=s.task_queue)
    try:
        result = await handle.result()
        ok = bool(result.report_path and result.chart_path)
        return {"q": question, "ok": ok, "steps": result.steps_used, "secs": time.monotonic() - t, "answer": result.summary}
    except Exception as e:
        return {"q": question, "ok": False, "steps": None, "secs": time.monotonic() - t, "answer": f"ERROR {e}"}


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=settings.llm_model)
    p.add_argument("--runs", type=int, default=1)
    # Ollama answers one request at a time by default; too many runs at once just queue
    # up behind each other until call_llm times out.
    p.add_argument("--concurrency", type=int, default=2)
    args = p.parse_args()
    s = replace(settings, llm_model=args.model)
    client = await connect(s)
    gate = asyncio.Semaphore(args.concurrency)

    async def limited(q):
        async with gate:
            return await run_one(client, q, s)

    rows = await asyncio.gather(*[limited(q) for q in QUESTIONS for _ in range(args.runs)])
    for r in rows:
        print(f"{'✓' if r['ok'] else '✗'} {r['secs']:6.1f}s steps={r['steps']}  {r['q']}\n    → {r['answer'][:200]}")
    ok = sum(r["ok"] for r in rows)
    print(f"\n{args.model}: {ok}/{len(rows)} produced report+chart; "
          f"median {sorted(r['secs'] for r in rows)[len(rows) // 2]:.0f}s per question")


if __name__ == "__main__":
    asyncio.run(main())
