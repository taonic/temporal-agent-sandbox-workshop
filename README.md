# Give Your Agent a Computer: Durable Sandboxes with Temporal

A 90-minute hands-on workshop for AI engineers who are new to Temporal. You build **Max**, a personal data-analyst agent with its own cloud computer (a [Daytona](https://daytona.io) sandbox). Max takes the headline ideas of today's personal agents: it keeps working after you close the app, asks before acting, sleeps when idle, and works in teams. It's all plain Python on the vanilla Temporal SDK; there's no agent framework.

| # | Challenge | What learners see | What they write |
|---|---|---|---|
| 1 | [Meet Max](challenges/01-meet-max/assignment.md) | An agent loop where every model call and sandbox call is a step in history; a bug *pauses* a run, and fixing it resumes the same run | Dispatch the model's tool calls |
| 2 | [Close the laptop](challenges/02-close-the-laptop/assignment.md) | Kill the worker mid-thought and Max carries on, with no duplicate sandbox; an idle sandbox sleeps and new data wakes it | The idle-suspend durable timer |
| 3 | [Ask before acting](challenges/03-ask-before-acting/assignment.md) | Human-in-the-loop that waits for free, rejects stale clicks, and times out politely | An Update handler, a validator, and a timed wait |
| 4 | [Many Maxes](challenges/04-many-maxes/assignment.md) | Parallel agents, each with its own sandbox; cancel the team and every sandbox is deleted | Fan out child workflows |
| ★ | [Bonus](challenges/05-bonus/assignment.md) | Schedules, versioning running agents, a new provider, snapshot branching | Open-ended |

Why it's built the way it is: [DESIGN.md](DESIGN.md).

## Architecture

![Max on Temporal: the app is a Temporal client that starts, signals, updates and queries workflows. A worker on task queue "max" runs TeamWorkflow, which starts one MaxWorkflow child per question. MaxWorkflow runs agent activities (call_llm, publish_report), which call an LLM over an OpenAI-compatible API, and reaches its child SandboxWorkflow through the call_sandbox activity, which sends Updates with a stable ID. SandboxWorkflow runs one provider activity per operation against a Daytona sandbox.](docs/architecture/max-architecture.png)

- **The app holds no state.** It's a Temporal client: it starts workflows, sends Signals (`new_data`, `dismiss`) and the `approve_publish` Update, and reads progress through Queries.
- **`MaxWorkflow` runs the agent loop.** Calls to the LLM (any OpenAI-compatible endpoint) and posting are activities; approvals and waiting for new data are durable waits.
- **`SandboxWorkflow` owns one sandbox from creation to deletion.** Workflow code can't send an Update to another workflow, so Max goes through the `call_sandbox` activity. Each request carries a stable update ID, so a retried activity doesn't run the same command twice.
- **Cleanup follows the workflow tree.** Cancelling a team flows down to every sandbox.

For an interactive version you can zoom, trace paths and export, open [docs/architecture/max-architecture.html](docs/architecture/max-architecture.html) in a browser. It was generated with [Archify](https://github.com/tt-a1i/archify) from [candidate.json](docs/architecture/candidate.json); edit that file and re-run `archify finalize` to update it.

## Run it locally

You need [uv](https://docs.astral.sh/uv/), the [Temporal CLI](https://docs.temporal.io/cli), [Ollama](https://ollama.com) and a Daytona API key.

```bash
cp .env.example .env                       # add DAYTONA_API_KEY, set LEARNER_ID
uv sync
```

### Start the model (Ollama)

Max's model calls go to any OpenAI-compatible endpoint. By default that's a local [Ollama](https://ollama.com):

```bash
# 1. Install: macOS app or `brew install ollama`; Linux: curl -fsSL https://ollama.com/install.sh | sh
# 2. Start the server, unless the Ollama desktop app is already running it:
ollama serve                               # listens on http://localhost:11434
# 3. In another terminal, download the model (about 3.4 GB, once):
ollama pull qwen3.5:4b
# 4. Check that it answers:
curl -s http://localhost:11434/v1/models
```

The matching `.env` settings, which are the defaults in `.env.example`:

```bash
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen3.5:4b
LLM_API_KEY=ollama                          # Ollama ignores it; hosted endpoints need a real key
```

- **Port 11434 is already taken** (for example by another project's Ollama container): run a second server with `OLLAMA_HOST=127.0.0.1:11435 ollama serve`, pull the model into it with `OLLAMA_HOST=127.0.0.1:11435 ollama pull qwen3.5:4b`, and set `LLM_BASE_URL=http://127.0.0.1:11435/v1`.
- **Using a hosted model instead:** point `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY` at any OpenAI-compatible service.
- **No model at all:** set `LLM_MODE=scripted`.
- **The model server is down:** Max doesn't fail. The `call_llm` activity keeps retrying with backoff, and the Temporal UI shows it as pending with `Connection error`. Start Ollama and the run carries on.

### Choose the code: finished Max or the challenges

`max_agent/` ships as the **finished Max**, with every challenge solved. The lab starts learners from `starter/` instead, with one TODO per challenge. On the starter, a run pauses at the first TODO (`NotImplementedError: TODO(ch01): handle the 'run_python' tool call`), which is what challenge 1 teaches. To do the challenges locally, switch first:

```bash
uv run python scripts/switch.py starter    # the workshop starting point: all TODOs open
uv run python scripts/switch.py solution   # back to the finished Max
uv run python scripts/switch.py status     # which one is in place
```

Only the three challenge files change. If you've edited them, your version is backed up to `.learner-backup/` first. Switch back to the solution before committing (`scripts/render.py --check` fails otherwise). Restart the worker after switching. A run that paused on a TODO resumes on its own once the solved worker picks it up. If you don't want to wait for Temporal's retry backoff, cancel it with `temporal workflow cancel -w <id>`.

### Start Temporal, the worker and the app

Use three terminals, and keep Ollama running:

```bash
temporal server start-dev
uv run max-worker
uv run max-app                             # http://localhost:8000
```

Max analyzes [datasets/coffee-chain](datasets/coffee-chain/README.md): four related tables (sales, promotions, shifts, inventory) with planted stories and deliberate data-quality defects. Runs work on a copy in `data/`; `uv run python -m max_agent.datasets reset` starts it over.

Without Daytona or a model, set `SANDBOX_PROVIDER=local` and `LLM_MODE=scripted`. Everything still works. The local provider is a plain directory, so it gives no isolation: use it only for development.

The CLI does the same things as the app:

```bash
uv run max ask "Which store had the highest revenue in the last 7 days?"
uv run max status <id> | approve <id> | reject <id> | new-data <id> | dismiss <id>
uv run max team "Q1" "Q2" "Q3"
```

## Repository map

```
max_agent/
  agent/       MaxWorkflow (agent loop, approvals), TeamWorkflow, LLM activity, prompts, scripted model
  sandbox/     SandboxWorkflow (one per sandbox), activities, providers/ (daytona, local), handle.py
  app/         FastAPI + htmx web app (the "Max" tab)
  cli.py, worker.py, client.py, config.py, datasets.py (working copy + "new data")
datasets/      coffee-chain/: generate.py (source of truth), committed CSVs, README (stories + defects)
authoring/     MASTER copies of files with learner TODOs (edit these, not max_agent/)
starter/       generated: the three TODO files as learners get them in the lab
solutions/     generated: chNN/ = code with challenges 1..N solved
challenges/    assignment.md + setup/check/solve/cleanup.sh per challenge (Instruqt lifecycle)
instruqt/      track/ (generated from challenges/), sandbox/ preset (VM config, setup script); see instruqt/README.md
docs/          architecture diagram (Archify source, HTML and PNG)
tests/         one check per challenge (local provider + scripted model) and provided-code tests
scripts/       render, verify_stages, build_track, build_snapshot, bench_llm, cleanup, schedule
```

## Authoring workflow

Three files contain learner TODOs: `agent/workflow.py`, `agent/team.py` and `sandbox/workflow.py`. Their masters live in `authoring/`, with markers:

```python
# @@solution ch02
...the code learners write...
# @@starter
...the TODO they start from...
# @@end
```

After editing a master:

```bash
uv run python scripts/render.py               # writes max_agent/ (finished), starter/ and solutions/chNN/
uv run python scripts/verify_stages.py        # each check fails before its solution, passes after
```

`verify_stages.py` prints a matrix. Challenge K's check must pass exactly when K ≤ stage:

```
stage  base  ch01  ch02  ch03  ch04
  0    pass  FAIL  FAIL  FAIL  FAIL
  1    pass  pass  FAIL  FAIL  FAIL
  ...
  4    pass  pass  pass  pass  pass
```

`max_agent/` is the fully solved code, so you develop against it directly. `--check` fails if `max_agent/` isn't the finished Max, or if `starter/` or `solutions/` are stale.

After editing a `challenges/*/assignment.md`, run `uv run python scripts/build_track.py` to refresh the Instruqt copy. [instruqt/README.md](instruqt/README.md) covers what to push when.

## Before a live session

- **Daytona quota:** Tier 1 orgs get 10 vCPU in total. A room of 30 learners with teams of 3 needs Tier 2 or higher (see DESIGN.md).
- **Model speed:** on the actual Instruqt machine type, run `uv run python scripts/bench_llm.py` (and `--model qwen3.5:9b`). Use `LLM_MODE=scripted` as the fallback if the model is slow or unreliable on the day.
- **After the session:** `uv run python scripts/cleanup.py --all-learners` deletes every sandbox labeled `app=max` on the org.
