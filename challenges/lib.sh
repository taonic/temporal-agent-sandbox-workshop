# shellcheck shell=bash
# Shared helpers for challenge lifecycle scripts (setup / check / solve / cleanup).
# Each script maps 1:1 onto an Instruqt lifecycle script; locally, run them from anywhere.

set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# Instruqt provides `fail-message`; locally, just print and exit.
if ! command -v fail-message >/dev/null 2>&1; then
  fail-message() { echo "✗ $*" >&2; exit 1; }
fi

# Run one challenge's check. Uses the local provider and the scripted model, so it's
# fast, free and deterministic: it grades your Temporal code, not the LLM's mood.
run_check() {
  uv run pytest -q -x -p no:cacheprovider "$@"
}

# Make sure challenges 1..N are solved, applying the official solution if not.
# Lets a learner who skipped or got stuck start the next challenge cleanly.
catch_up() {
  local upto="$1"
  local checks=(tests/test_ch01_meet_max.py tests/test_ch02_idle_suspend.py tests/test_ch03_approval.py tests/test_ch04_team.py)
  [ "$upto" -ge 1 ] || return 0
  if ! run_check "${checks[@]:0:$upto}" >/dev/null 2>&1; then
    echo "Applying the solution for challenges 1-$upto so you can carry on."
    cp -R "solutions/ch$(printf %02d "$upto")/." "$REPO/"
  fi
}

# Code changes to a workflow can't be replayed against runs started with the old
# code, so retire the learner's running Maxes before a challenge changes workflows.
retire_runs() {
  uv run python scripts/cleanup.py >/dev/null 2>&1 || true
}

# Every challenge starts from the same world: no worker, no sandboxes, an empty
# Temporal and fresh data (instruqt/bin/lab-reset). The learner's code is kept.
# Locally, where the services aren't ours to restart, only the data is reset.
fresh_start() {
  if systemctl cat temporal >/dev/null 2>&1; then
    "$REPO/instruqt/bin/lab-reset"
  else
    uv run python -m max_agent.datasets reset
  fi
}

restart_worker_hint() {
  echo "Restart your worker (Ctrl-C, then: uv run max-worker) to load the new code."
}
