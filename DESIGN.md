# Design: Give Your Agent a Computer

The decisions behind this workshop, as agreed during planning (2026-10-03). Read this before changing the scenario, the challenge order or the architecture.

## Audience and format

- **Who:** AI engineers who are new to Temporal.
- **How long:** 90 minutes with an instructor, 4 challenges of about 15 minutes each plus a bonus. It must also work self-paced.
- **Style:** mostly run, observe and break things (kill the worker, cancel runs, let sandboxes idle), with one small TODO per challenge.
- **Platform:** Instruqt eventually. For now this repo runs end to end locally, and its scripts map onto Instruqt's lifecycle scripts.

## Scenario: Max

Max is a personal analyst agent with its own computer. It borrows the headline ideas of the personal agents that launched in 2026:

| Personal-agent idea | Where it shows up |
|---|---|
| Each agent gets its own cloud computer | One Daytona sandbox per Max, owned by a `SandboxWorkflow` |
| Keeps working after you close the app | Kill the worker or the app; Max resumes (challenge 2) |
| Comes back for approval before acting | Approve or reject before posting to `#analytics` (challenge 3) |
| Several agents in parallel | A team of Maxes, one per question (challenge 4) |
| Reruns on new data / scheduled work | "Drop in tomorrow's sales" button (challenge 2); Schedule (bonus) |
| Watch it work | Live step feed, sandbox state, Temporal UI |
| Sandboxing untrusted actions | Max's code runs with networking blocked (`network_block_all`) |

Max analyzes a synthetic, seeded coffee chain (`datasets/coffee-chain/`): four tables (`sales`, `promotions`, `shifts`, `inventory`, at most 8 columns each) joined on date and store.
- **Planted stories make answers checkable:** promotion outcomes, weekend overstaffing, oat-milk waste after a stockout, rain and Cold Brew, Castro's matcha surge.
- **Deliberate defects:** duplicates, a misspelled store, missing days and a refund, both in the history and on every third new day. The preamble preloads every table but cleans nothing, so the "code fails, model reads the error, retries" loop happens for real.
- **Committed CSVs:** `generate.py` is the source of truth, and a test keeps the CSVs in sync with it. Runs use a working copy in `data/`, and "new data" appends a day to every daily table there.
- **Room for more:** the loader takes a dataset name, so another domain could be added later. The prompt is still coffee-specific.

Errand-style agents (a browser doing shopping or bookings) are deferred. The tool list and the provider interface leave room for them; nothing more is built yet.

## Architecture

```
 web app / CLI ──start, signal, update, query──▶ MaxWorkflow (the reasoning)
                                                  │  call_llm activity ──▶ Qwen via OpenAI-compatible API
                                                  │  call_sandbox activity ──update──▶ SandboxWorkflow (child)
                                                  │                                    │ provider activities
                                                  │                                    ▼
                                                  │                                 Daytona sandbox (the hands)
 TeamWorkflow ──child workflows──▶ MaxWorkflow × N
```

- **Vanilla Temporal Python SDK, no agent framework.** The agent loop lives in `MaxWorkflow`. Every model call and every sandbox operation is an activity, so all of them show up in history.
- **The reasoning runs in the workflow; the code runs in the sandbox.** The model never touches Temporal or the host. It only gets `run_python` and `finish`.
- **`SandboxWorkflow` is a Python port of the Go `sandbox-orchestration-harness` design:**
  - It is an entity workflow, one per sandbox, started as a child workflow with `ParentClosePolicy.REQUEST_CANCEL`.
  - Updates with validators (`init`, `exec`, `upload`, `download`, `suspend`, `resume`), a `stop` signal and a `state` query.
  - Auto-resume when an operation arrives for a suspended sandbox.
  - Idle auto-suspend. The workflow owns this: Daytona's `auto_stop_interval=0`, because Daytona only counts API calls as activity.
  - Cleanup on stop and on cancel.
  - Continue-as-new after 200 operations, or when Temporal suggests it.
  - Not ported: the snapshot-based suspend fallback and the leftover "ephemeral worker" task-queue code.
- **Workflows reach `SandboxWorkflow` through the `call_sandbox` activity.** Workflow code can't send an Update to another workflow, so the activity uses the client's `execute_update` with an update ID generated in the workflow, which stays stable across retries.
- **Providers:** `SandboxProvider` interface (`max_agent/sandbox/providers`). `daytona` is the real one; `local` (a directory plus subprocesses, no isolation) runs tests and checks. Sandbox creation is idempotent because the name comes from the workflow ID: on a conflict, look up the existing sandbox.
- **Artifacts:** the report and chart are downloaded into `artifacts/<workflow-id>/runN/`. Only file paths go into workflow history.
- **Configuration:** processes read the environment (`.env`); workflows never do. The workflow input records *what* to use (model name, provider, timeouts). The worker's environment decides *where* (`LLM_BASE_URL`, API keys), so secrets never reach history.

## Model

- **Default:** `qwen3.5:4b` on Ollama, with thinking turned off (`reasoning_effort="none"`), through the OpenAI-compatible API. Any OpenAI-compatible endpoint can be swapped in with `LLM_BASE_URL` / `LLM_MODEL`.
- **Helping a small model:** every script gets a preamble (`prompts.PREAMBLE`) that loads `df` with parsed dates and sets up `today`, `plt` and `out/`. The prompt is short and there are only two tools.
- **Scripted mode:** `LLM_MODE=scripted` replays a fixed plan through the same activity. Checks use it, and it's the fallback for a live session.
- **Measured on 2026-10-03** (Apple-silicon Mac, Ollama, not Instruqt): about 8–10 s per call. 3 of 4 benchmark questions produced a correct report and chart in 4 steps each; the "growth over two weeks" question ran out of steps.
- **Still open:** run `scripts/bench_llm.py` on an n2-standard-8 Instruqt VM with CPU only, and switch to `qwen3.5:9b` if 4B is too unreliable there.

## Infrastructure (Instruqt)

- A Temporal dev server in the VM, started with `--dynamic-config-value 'history.workflowTaskRetryMaxInterval="5s"'`. Its UI is a tab.
  Without that setting, a paused run waited 2 minutes to resume after a fix that took the learner 4 minutes, because the default backoff keeps growing up to a cap of minutes. With it, the run resumed in 16 s.
- Ollama runs natively in the VM with the model pre-pulled into the image. Instruqt has no GPUs, so it runs on CPU, on an n2-standard-8 (8 vCPU / 32 GB). On n2-standard-4, warming the model alone took about 2.5 minutes of setup.
- **Daytona:** one org key, supplied as a VM environment variable in `instruqt/sandbox/config.yml`, shared by all learners.
  - Every sandbox is labeled `app=max`, `learner=$LEARNER_ID` and `workflow=<id>`. The cleanup script deletes by label.
  - **The org needs Tier 2 or higher.** Tier 1's 10 vCPU fits about 10 sandboxes in total, and a room of 30 learners with a team of 3 each needs up to about 120.
  - Sandboxes are 1 vCPU / 1 GiB, built from the prebuilt `max-analyst-py` snapshot (`scripts/build_snapshot.py`, run once per org).
  - Fan-out is capped at 3 questions.

## Verified facts (2026-10-03)

- **Daytona:**
  - Creating a sandbox with a duplicate name raises `DaytonaConflictError`, and `get(name)` works.
  - Files survive a stop and restart; a stop takes about 9 s and a start about 6 s.
  - `fork()` is **not** supported on container sandboxes, so the fork bonus has to go through `create_snapshot`.
  - A missing file on download raises a generic `DaytonaError` ("file not found").
- **Bug handling:** Max deletes its sandbox only when the run is really ending (cancellation or a Temporal `FailureError`). A plain bug pauses the run and must leave the sandbox alone. Otherwise the cleanup lands in history and the fixed code can't replay it (we hit this).
- **End to end on real Daytona and Qwen:**
  - Cancelling Max deletes its sandbox.
  - Killing the worker mid-run resumes without repeating steps or creating a second sandbox.
  - An idle sandbox suspends (Daytona `STOPPED`) and auto-resumes when new data arrives.

## Code layout and authoring

- `authoring/` holds the master copies of the three files that contain learner TODOs, with `# @@solution chNN / # @@starter / # @@end` markers.
- `scripts/render.py` writes the finished versions into `max_agent/`, the starter versions into `starter/` and each stage into `solutions/chNN/`. Never edit those generated copies by hand.
- The repo runs the finished Max. The Instruqt sandbox lays `starter/` over `max_agent/` so learners begin with every TODO open.
- `scripts/verify_stages.py` checks that each challenge's check fails before its solution is applied and passes after.
