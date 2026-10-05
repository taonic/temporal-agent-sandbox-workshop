---
slug: ask-before-acting
type: challenge
title: "3 · Ask before acting"
teaser: Max never posts on its own. Make it wait for a human for seconds or for days, at no cost and safe from restarts.
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

# Ask before acting

A good personal agent checks with you before it sends an email or buys something, and lets you decide per app whether an action is auto-approved, blocked or needs your permission. **Agents that act in the world need a human in the loop.**

That sounds simple until you build it. The human might answer in 5 seconds or in 5 hours. Your server might be redeployed in between. The approve button might be clicked twice, or after the agent has already moved on.

Max is supposed to post its findings to the team's **#analytics** channel, but only after you approve. Right now it never posts at all (see the "Skipping publish" step).

## 1. Retire the running Maxes

You're changing `MaxWorkflow`, so retire the runs that use the old code:

```bash
uv run python scripts/cleanup.py
```

## 2. Let people answer: an Update handler

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

## 3. Wait for the human (but not forever)

Find the first `TODO(ch03)` in `_ask_to_publish` and replace the "Skipping publish" line:

1. Set `self._decision = None` and `self._phase = Phase.AWAITING_APPROVAL`.
2. `await workflow.wait_condition(lambda: self._decision is not None, timeout=...)`, using `self._inp.approval_timeout_s`. On `asyncio.TimeoutError`, note it and return without posting.
3. If approved, run the `publish_report` activity with a `PublishRequest` (`post_id=f"{workflow.info().workflow_id}/run{self._reruns}"`) and set `self._published = True`.

> Why a `post_id`? Activities can be retried. `publish_report` uses the ID to make sure a retry never posts the same report twice.

(The full solution also sets `self._approval_deadline` so the app can show a countdown, and handles a dismiss arriving during the wait.)

## 4. Try it

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
