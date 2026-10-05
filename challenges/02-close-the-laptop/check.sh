#!/usr/bin/env bash
source "$(dirname "$0")/../lib.sh"
run_check tests/test_ch02_idle_suspend.py \
  || fail-message "The sandbox doesn't suspend when idle (or suspends while busy). Look for TODO(ch02) in max_agent/sandbox/workflow.py."
