#!/usr/bin/env bash
# Challenge 1 setup: nothing to change, the track setup already prepared the starter code.
source "$(dirname "$0")/../lib.sh"
uv run python -m max_agent.datasets reset
