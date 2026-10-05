---
slug: many-maxes
type: challenge
title: "4 · Many Maxes"
teaser: Fan out a team of agents, each with its own computer, then cancel the lot and watch every sandbox get cleaned up.
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
difficulty: intermediate
timelimit: 1200
---

# Many Maxes

Muse Spark runs several sub-agents on one task in parallel, and a Dot juggles several projects at once. Parallel agents are faster, but each one has its own computer. When something goes wrong, every one of those computers has to be cleaned up, not just most of them.

When you ask Max more than one question (one per line, up to three), the app starts a **TeamWorkflow** (`max_agent/agent/team.py`). Each question goes to its own **child** `MaxWorkflow`, with its own sandbox:

```
TeamWorkflow
 ├─ MaxWorkflow  (question 1) ── SandboxWorkflow ── Daytona sandbox
 ├─ MaxWorkflow  (question 2) ── SandboxWorkflow ── Daytona sandbox
 └─ MaxWorkflow  (question 3) ── SandboxWorkflow ── Daytona sandbox
```

## 1. Watch the slow version

Ask three questions at once in the **Max** tab:

```
Which store had the highest revenue in the last 7 days?
Does rainy weather change Cold Brew sales?
Is SoMa busier on weekdays or weekends?
```

The team page shows the members. Only one is working; the others wait their turn. Open `max_agent/agent/team.py` to see why: `workflow.execute_child_workflow` starts a child **and waits for it to finish** before the loop moves on.

## 2. Make it parallel

Find `TODO(ch04)`. Start every member first, then wait for all of them together:

```python
handles = [
    await workflow.start_child_workflow(MaxWorkflow.run, member, id=member_id, static_summary=member.question)
    for member, member_id in zip(members, self._member_ids)
]
outcomes = await asyncio.gather(*handles, return_exceptions=True)
```

`return_exceptions=True` means one analyst failing doesn't sink the whole team. The code after your TODO already turns failures into a "didn't finish" section of the team report.

Restart the worker (team runs are short, so there's nothing to retire) and ask the three questions again. All three now work at once, each on its own computer. In the **Temporal UI**, open the team workflow and follow the tree of child workflows.

## 3. Pull the plug

Ask three questions again. While they're working, click **Cancel team**.

Cancellation flows down the tree. Watch it in the Temporal UI:

1. The team is cancelled, so each child **Max** gets a cancellation request.
2. Each Max's `finally` block tells its sandbox to stop and waits until it has. The sandbox workflow deletes the Daytona sandbox, then *completes*.
3. As a safety net, sandbox workflows are started with `ParentClosePolicy.REQUEST_CANCEL`. If a Max ever died without cleaning up, its sandbox workflow would be cancelled, and it deletes its sandbox before reporting itself cancelled.

Confirm that nothing leaked:

```bash
uv run python scripts/cleanup.py --dry-run
```

None of the team's sandboxes should be listed. Try the same with a worker crash: start a team, kill the worker, cancel the team in the Temporal UI, then start the worker. The cleanup still happens, because the cancellation waits in Temporal until a worker can act on it.

## Check

Click **Check**. It verifies that team members overlap in time, and that cancelling a team leaves no sandbox behind.

## Recap

| You built | Temporal feature | Why it matters for agents |
|---|---|---|
| Agent loop with model calls as activities | Workflows + activities, event history | Crash anywhere, resume exactly; never repeat (or re-pay for) a model call |
| One workflow per sandbox | Entity workflow, Updates with validators | One source of truth for each computer's state; impossible requests are rejected |
| Idle suspend, auto-resume | Durable timers | Pay only for compute you use, even across hours of waiting |
| Approvals | Updates + `wait_condition` with a timeout | Human-in-the-loop that costs nothing and survives deploys |
| Teams | Child workflows, cancellation, parent close policy | Fan out safely; every sandbox is cleaned up, every time |
