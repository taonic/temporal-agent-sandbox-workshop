#!/usr/bin/env bash
source "$(dirname "$0")/../lib.sh"
run_check tests/test_ch04_team.py \
  || fail-message "The team isn't working in parallel yet (or left a sandbox behind). Look for TODO(ch04) in max_agent/agent/team.py."
