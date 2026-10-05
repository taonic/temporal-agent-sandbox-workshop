#!/usr/bin/env bash
source "$(dirname "$0")/../lib.sh"
run_check tests/test_ch01_meet_max.py \
  || fail-message "Max can't finish a run yet. Look for TODO(ch01) in max_agent/agent/workflow.py, and check the Temporal UI for a failed workflow task."
