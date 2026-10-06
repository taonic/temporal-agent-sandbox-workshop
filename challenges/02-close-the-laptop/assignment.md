---
slug: close-the-laptop
type: challenge
title: "2 · Close the laptop"
teaser: Crash Max mid-thought and watch it carry on. Then stop paying for a computer nobody is using.
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

# Close the laptop

The pitch for personal agents is that **they keep working after you close the app**. Behind that promise there are two hard problems:

1. **Crashes.** The machine running your agent dies halfway through a task. Does the agent start over? Does it leak its sandbox, or create a second one?
2. **Cost.** An agent with its own computer is waiting most of the time: for data, for people, for tomorrow. A sandbox that runs while nobody uses it is money on fire.

## Start the worker

Every challenge starts fresh: setup stopped the previous worker, deleted your sandboxes, emptied the Temporal UI and reset the data. Your code is as you left it. The **Worker** tab is empty, so start the worker there and leave it running:

```bash
uv run max-worker
```

Stuck later? Run `lab-reset` in the **Shell** tab to start this challenge over the same way. It never touches your code.

## Part A: Crash Max (no code changes)

In the **Max** tab, ask:

> Is SoMa busier on weekdays or weekends?

As soon as the first `run_python` step appears, **kill the worker**: press `Ctrl-C` in the **Worker** tab. For a harsher crash, run this in the **Shell** tab:

```bash
pkill -9 -f max-worker
```

Now look around:

- **Max app:** Max is frozen mid-run. Nothing is lost; nothing is running.
- **Temporal UI:** open the run. Its next step (probably `call_llm`) is *pending*. Nobody's working on it, but Temporal remembers that it needs doing.
- **Shell:** list your sandboxes on Daytona:

  ```bash
  uv run python scripts/cleanup.py --dry-run
  ```

  There's exactly one sandbox for this run.

Start the worker again (`uv run max-worker`). Max picks up **exactly where it stopped**: earlier steps aren't repeated, and there's no second sandbox. If the crash hit during a model call, that call is retried. `call_llm` sends heartbeats, so Temporal noticed the dead worker within 30 seconds instead of waiting out the full 10-minute timeout.

> Why no duplicate sandbox? Creating a sandbox is an activity, and activities can be retried. The sandbox is named after the workflow ID, so a retried create finds the existing sandbox instead of making a second one (see `max_agent/sandbox/providers/daytona.py`).

## Part B: Stop paying for an idle computer

Let Max finish. It ends up **waiting for new data**, perhaps for hours. Look at the **Max's computer** card: the sandbox is still `running`. It will stay that way all day.

You might think: Daytona has its own auto-stop, so use that. But Daytona only counts *API calls* as activity. It can't tell "Max is waiting for a human" apart from "Max's 20-minute script is still running". **Your workflow knows exactly when Max is idle**, so the workflow should decide.

### 1. Retire the running Maxes first

You're about to change workflow code. Temporal replays a run's history through the code to rebuild its state, so a run that started on the old code can't continue on the new code. (Doing that safely is called *versioning*: see the bonus challenge.) In the **Shell** tab:

```bash
uv run python scripts/cleanup.py
```

This *cancels* your runs, and each sandbox workflow deletes its sandbox as it shuts down.

### 2. Write the idle timer

Open `max_agent/sandbox/workflow.py` and find `TODO(ch02)` in `_watch_for_idle`. Right now it waits, without any time limit, for the sandbox to be used again. Give that wait a deadline:

```python
try:
    await workflow.wait_condition(used_again, timeout=timedelta(seconds=self._s.init.idle_timeout_s))
except asyncio.TimeoutError:
    ...  # nobody used the sandbox in time: take self._lock and, if still RUNNING, await self._suspend()
```

`wait_condition` with a timeout is a **durable timer**. It's stored by the Temporal server, not in your process, so it survives worker restarts and costs nothing while it waits. It could just as well be 6 hours.

<!-- @@solution ch02 -->

### 3. Watch Max's computer fall asleep

Restart the worker and ask Max a new question. When Max is *waiting for new data*, watch the card: after `IDLE_TIMEOUT_S` (60s) the state changes to **asleep 💤**. In Daytona, the sandbox is now stopped.

Click **Drop in tomorrow's sales**. Max uploads the new data to its sandbox. The sandbox workflow sees an operation arrive for a sleeping sandbox, **wakes it up first**, then runs it (look at *Suspends / resumes*). Max reruns the analysis on its own computer, with the files still where it left them.

## Check

Click **Check**. It verifies that an idle sandbox suspends, a busy one doesn't, and a suspended one wakes up when it's needed.
