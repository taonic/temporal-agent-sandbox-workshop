#!/usr/bin/env bash
source "$(dirname "$0")/../lib.sh"
run_check tests/test_ch03_approval.py \
  || fail-message "Approvals aren't working yet. Look for both TODO(ch03) markers in max_agent/agent/workflow.py: the approve_publish update and the wait in _ask_to_publish."
