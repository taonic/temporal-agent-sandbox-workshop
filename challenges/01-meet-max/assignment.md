---
slug: meet-max
type: challenge
title: "1 · Meet Max"
teaser: Give an AI agent its own computer, and watch every thought and action land in a durable history.
tabs:
- title: Worker
  type: terminal
  hostname: workstation
  workdir: /root/workshop
- title: Shell
  type: terminal
  hostname: workstation
  workdir: /root/workshop
- title: Code
  type: code
  hostname: workstation
  path: /root/workshop
- title: Max
  type: service
  hostname: workstation
  port: 8000
- title: Temporal UI
  type: service
  hostname: workstation
  port: 8233
difficulty: basic
timelimit: 1200
---

# Meet Max

Personal agents now get **their own cloud computer**. You hand one a task, close the app, and it keeps working: running code, waiting on people, coming back when it needs an approval.

The model is the easy part. The hard part is everything around it:

- What happens when the machine running the agent crashes halfway through?
- Who deletes the sandbox when the agent is done, or dies?
- How does an agent wait three hours for a human without burning money?

In this workshop you'll build **Max**: a personal data analyst with its own computer (a [Daytona](https://daytona.io) sandbox), orchestrated with plain [Temporal](https://temporal.io). There's no agent framework; it's just Python.

## How Max is built

```
You (web app) ──▶ MaxWorkflow ─────────────▶ call_llm activity ──▶ Qwen (running locally)
                      │ "the brain": the agent loop
                      └──▶ SandboxWorkflow ──▶ Daytona sandbox
                           "the computer": one workflow per sandbox
```

- **MaxWorkflow** (`max_agent/agent/workflow.py`) runs the agent loop: ask the model what to do, do it, repeat.
- **Activities** are the steps that touch the outside world: calling the model, creating a sandbox, running code. Temporal records each one's result.
- **SandboxWorkflow** (`max_agent/sandbox/workflow.py`) owns one sandbox from birth to deletion. Max talks to it through **Updates** (requests that return a result). It's provided for you; you'll extend it in challenge 2.

## 1. Start Max's worker

The **worker** is the process that runs your workflow and activity code. In the **Worker** tab:

```bash
uv run max-worker
```

Leave it running.

## 2. Ask Max something

Open the **Max** tab and ask:

> Which store had the highest revenue in the last 7 days?

Max gets its computer (a real Daytona sandbox), uploads the sales data and asks the model what to do... and then it gets stuck in *analyzing*.

## 3. Find out why in the Temporal UI

Open the **Temporal UI** tab, then click your `max-…` workflow.

- In the timeline you can see the child `sandbox-max-…` workflow that was started, the `sandbox.init` and `sandbox.upload` steps, and a completed `call_llm` activity. Expand it: that's the model's actual reply, asking for `run_python`.
- Then a **Workflow Task Failed** in red: `NotImplementedError: TODO(ch01)`.

This is a key Temporal idea. **A bug in workflow code doesn't fail the workflow; it pauses it.** Temporal keeps retrying that step, and everything that already happened (the sandbox and the model's reply) is safely recorded. Fix the code, and the run continues from where it stopped.

## 4. Teach Max to act

Open `max_agent/agent/workflow.py` in the **Code** tab and find `TODO(ch01)` in `_handle_tool_call`. The model asks for tools by name. Handle both of them:

- `run_python`: run `call.arguments["code"]` with `await self._run_python(code)` and return the result. That string is what the model sees next.
- `finish`: save `call.arguments["summary"]` in `self._finish_summary` (the loop stops once it's set), record it with `self._add_step("finish", summary)`, and return `"ok"`.
- Anything else: return a short message saying that tool doesn't exist.

## 5. Restart the worker and watch the stuck run continue

In the **Worker** tab press `Ctrl-C`, then run `uv run max-worker` again.

You don't need to start a new run. Go back to the Max tab: within a few seconds, **the same run picks up where it stopped**. (Temporal retries a failing workflow task with a growing backoff. This workshop's server caps it at 5 seconds; in production the wait can be several minutes.) In the Temporal UI, notice that the first `call_llm` was **not** called again. Its result came from history. In production, that's a model call you don't pay for twice.

Watch Max work. Each `run_python` step is model-written code running inside the sandbox. Expand a step to see the code and its output. A small model makes mistakes; when its code fails, it reads the error and tries again.

> **If the model misbehaves**, set `LLM_MODE=scripted` in `.env` and restart the worker. Max then follows a fixed plan through the very same activities, so the Temporal story is unchanged.

## 6. Look under the hood

Click into the `sandbox-max-…` workflow in the Temporal UI:

- Every operation (`init`, `upload`, `exec`, `download`) is an **Update** with a validator. A request that makes no sense right now, such as running code before the sandbox exists, is rejected before it touches history.
- The **Queries** tab, `state`: the sandbox's lifecycle, provider and counters. The Max app reads this to draw the "Max's computer" card.

## Check

Click **Check**. It runs Max against a local stand-in sandbox and a scripted model, so it grades your Temporal code, not the model's luck.

Leave Max waiting for new data: you'll need it in challenge 2.
