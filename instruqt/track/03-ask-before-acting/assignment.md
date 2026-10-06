---
slug: ask-before-acting
id: g37kizsfby0b
type: challenge
title: 3 · Ask before acting
teaser: Max never posts on its own. Make it wait for a human for seconds or for days,
  at no cost and safe from restarts.
tabs:
- id: c7dwlkkb01qi
  title: Worker
  type: terminal
  hostname: workstation
  workdir: /root/workshop
- id: xl2icoyinz6a
  title: Shell
  type: terminal
  hostname: workstation
  workdir: /root/workshop
- id: eo4ghi6vmyy8
  title: Code
  type: code
  hostname: workstation
  path: /root/workshop
- id: ttjodfhpxs7d
  title: Max
  type: service
  hostname: workstation
  port: 8000
- id: yfy7shd9cf72
  title: Temporal UI
  type: service
  hostname: workstation
  port: 8233
difficulty: intermediate
timelimit: 1200
enhanced_loading: null
---

# Ask before acting

A good personal agent checks with you before it sends an email or buys something, and lets you decide per app whether an action is auto-approved, blocked or needs your permission. **Agents that act in the world need a human in the loop.**

That sounds simple until you build it. The human might answer in 5 seconds or in 5 hours. Your server might be redeployed in between. The approve button might be clicked twice, or after the agent has already moved on.

Max is supposed to post its findings to the team's **#analytics** channel, but only after you approve. Right now it never posts at all (see the "Skipping publish" step).

## Start the worker

Every challenge starts fresh: setup stopped the previous worker, deleted your sandboxes, emptied the Temporal UI and reset the data. Your code is as you left it. The **Worker** tab is empty, so start the worker there and leave it running:

```bash
uv run max-worker
```

Stuck later? Run `lab-reset` in the **Shell** tab to start this challenge over the same way. It never touches your code.

## 1. Let people answer: an Update handler

Open `max_agent/agent/workflow.py` and find the second `TODO(ch03)`, near the bottom of the class. Add an **Update handler**:

```python
@workflow.update
def approve_publish(self, decision: Decision) -> str:
    ...  # store the decision, return a short message ("posting" / "not posting")

@approve_publish.validator
def validate_approve_publish(self, decision: Decision) -> None:
    ...  # raise ApplicationError unless Max is AWAITING_APPROVAL and has no decision yet
```

Temporal has three ways to talk to a running workflow:

| | Changes state? | Returns a result? | Can be rejected? |
|---|---|---|---|
| **Query** (`status`) | no | yes | no |
| **Signal** (`new_data`, `dismiss`) | yes | no, fire-and-forget | no |
| **Update** (`approve_publish`) | yes | yes | **yes, by a validator** |

An approval should tell the clicker whether it counted, so it's an Update. The **validator** runs before anything is written to history. A late or duplicate click gets a clear "no" and leaves no trace.

<details>
<summary>Show the complete code</summary>

In `max_agent/agent/workflow.py`, replace the `TODO(ch03)` comments in the `MaxWorkflow` class with this, indented to match:

```python
@workflow.update
def approve_publish(self, decision: Decision) -> str:
    self._decision = decision
    return "posting" if decision.approve else "not posting"

@approve_publish.validator
def validate_approve_publish(self, decision: Decision) -> None:
    # Validators run before anything is written to history: a late or
    # duplicate click is rejected without leaving a trace.
    if self._phase != Phase.AWAITING_APPROVAL or self._decision is not None:
        raise ApplicationError("Max isn't waiting for approval right now", type="NotAwaitingApproval")
```

</details>

## 2. Wait for the human (but not forever)

Find the first `TODO(ch03)` in `_ask_to_publish` and replace the "Skipping publish" line:

1. Set `self._decision = None` and `self._phase = Phase.AWAITING_APPROVAL`.
2. `await workflow.wait_condition(lambda: self._decision is not None, timeout=...)`, using `self._inp.approval_timeout_s`. On `asyncio.TimeoutError`, note it and return without posting.
3. If approved, run the `publish_report` activity with a `PublishRequest` (`post_id=f"{workflow.info().workflow_id}/run{self._reruns}"`) and set `self._published = True`.

> Why a `post_id`? Activities can be retried. `publish_report` uses the ID to make sure a retry never posts the same report twice.

(The full solution also sets `self._approval_deadline` so the app can show a countdown, and handles a dismiss arriving during the wait.)

<details>
<summary>Show the complete code</summary>

In `max_agent/agent/workflow.py`, replace the `TODO(ch03)` comments and the placeholder code under them in `_ask_to_publish` with this, indented to match:

```python
self._decision = None
self._phase = Phase.AWAITING_APPROVAL
timeout = timedelta(seconds=self._inp.approval_timeout_s)
self._approval_deadline = (workflow.now() + timeout).isoformat(timespec="seconds")
try:
    # Wait for a person. Could be seconds, could be days: either way it
    # costs nothing and survives restarts.
    await workflow.wait_condition(lambda: self._decision is not None or self._dismissed, timeout=timeout)
except asyncio.TimeoutError:
    self._note("Nobody approved in time; keeping the report, not posting it")
    return
finally:
    self._approval_deadline = None

if self._decision is None:  # dismissed while waiting
    return
if not self._decision.approve:
    self._note(f"{self._decision.by} said no; not posting")
    return
self._phase = Phase.PUBLISHING
await workflow.execute_activity(
    publish_report,
    PublishRequest(
        post_id=f"{workflow.info().workflow_id}/run{self._reruns}",
        workflow_id=workflow.info().workflow_id,
        result=self._result,
        approved_by=self._decision.by,
    ),
    start_to_close_timeout=timedelta(seconds=30),
)
self._published = True
self._note(f"Posted to #analytics (approved by {self._decision.by})")
```

</details>

## 3. Try it

Restart the worker and ask Max a question. When it's done you'll see **Max wants to post this to #analytics**:

- Click **Approve**. The report shows up in **#analytics** (top nav).
- Click **Approve** again. The page tells you it was rejected: that's your validator.
- From the **Shell** tab, try the same thing the app does:

  ```bash
  uv run max approve <workflow-id>
  ```

**Let it time out.** Click **Drop in tomorrow's sales**, then don't answer. After `APPROVAL_TIMEOUT_S` (3 minutes; lower it in `.env` if you're impatient), Max notes that nobody approved, keeps the report and doesn't post.

**Bonus experiment:** while Max is waiting for approval, stop the worker. Click **Approve** in the app: the request waits, because an Update needs a worker to run its validator. Start the worker, and the approval goes through.

## Check

Click **Check**. It verifies that Max waits for approval, posts exactly once when approved, turns away a second click, and doesn't post when rejected or ignored.
