#!/usr/bin/env bash
source "$(dirname "$0")/../lib.sh"
retire_runs
cp -R solutions/ch03/. "$REPO/"
restart_worker_hint
