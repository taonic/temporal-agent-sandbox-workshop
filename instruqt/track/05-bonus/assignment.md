---
slug: bonus
id: 0lsvmvbixxtd
type: challenge
title: "Bonus · Make Max your own"
teaser: Schedules, safe upgrades of running agents, a second sandbox provider, or try-three-fixes-and-keep-the-best.
tabs:
- id: xjjsqedfmbwv
  title: Worker
  type: terminal
  hostname: workstation
  workdir: /root/workshop
- id: yyne90frhqci
  title: Shell
  type: terminal
  hostname: workstation
  workdir: /root/workshop
- id: ua8tdpfv0n1l
  title: Code
  type: code
  hostname: workstation
  path: /root/workshop
- id: heur1luu1zqy
  title: Max
  type: service
  hostname: workstation
  port: 8000
- id: qytcrickimec
  title: Temporal UI
  type: service
  hostname: workstation
  port: 8233
difficulty: advanced
timelimit: 1800
---

# Make Max your own

Pick any of these. They're independent of each other, and none are graded.

## Start the worker

Every challenge starts fresh: setup stopped the previous worker, deleted your sandboxes, emptied the Temporal UI and reset the data. Your code is as you left it. The **Worker** tab is empty, so start the worker there and leave it running:

```bash
uv run max-worker
```

Stuck later? Run `lab-reset` in the **Shell** tab to start this challenge over the same way. It never touches your code.

## A. Every morning, without being asked (Schedules)

A personal agent reruns your analysis when new data lands. Give Max a schedule:

```bash
uv run python scripts/schedule.py create "How did yesterday compare with the day before?" --every 5m
uv run python scripts/schedule.py trigger   # don't wait for the first tick
```

In the Temporal UI, open **Schedules**. Each tick starts a fresh Max with its own sandbox, and it asks for approval as usual. The overlap policy is `SKIP`, so if you ignore one run, the next tick is skipped instead of piling up Maxes. Read `scripts/schedule.py`, then try pausing the schedule in the UI. Delete it when you're done:

```bash
uv run python scripts/schedule.py delete
```

## B. Upgrade Max without retiring it (versioning)

In challenge 2 you retired running Maxes before changing workflow code. In production you can't: some Max is always waiting on someone.

Keep a Max waiting for new data, then change what it does on a rerun. For example, post a note before rerunning. Guard the change with a patch:

```python
if workflow.patched("note-before-rerun"):
    self._note("Fresh data! Taking another look.")
```

Restart the worker and click **Drop in tomorrow's sales**: the old run takes the new path, safely. Now try the same change *without* `patched` on a fresh run, and look for the non-determinism error in the Temporal UI. That's Temporal refusing to replay history through code that doesn't match it.

## C. A second sandbox provider

The provider interface is `max_agent/sandbox/providers/base.py`: create, suspend, resume, destroy, exec, upload and download. `local.py` is a complete implementation in about 80 lines. Add one for E2B, Modal or another sandbox you use, register it in `providers/__init__.py`, then set `SANDBOX_PROVIDER` in `.env`. No workflow code changes. Ideas for making it robust:

- Make `create` idempotent: what does your provider do with a duplicate name?
- Raise `PermanentProviderError` for failures that retrying won't fix.

## D. Try three fixes, keep the best (snapshots)

Agents get better results when they can branch: try several approaches from the same starting state and keep the winner.

Daytona doesn't support `fork()` for container sandboxes (we tried), but `sandbox.create_snapshot(name)` can snapshot a sandbox (container sandboxes must be stopped first), and new sandboxes can start from that snapshot. Check the current Daytona docs for the exact behavior. Sketch it:

1. Add `snapshot` and create-from-snapshot operations to the provider and to `SandboxWorkflow` (as Updates with validators).
2. Write a `BranchWorkflow` that snapshots Max's sandbox, starts three child Maxes from the snapshot with different instructions, and keeps the best report.
3. Make sure every branch's sandbox, *and the snapshot*, gets cleaned up, even on cancel.

The Go `sandbox-orchestration-harness` this workshop borrows from has a snapshot-based design to compare with.
