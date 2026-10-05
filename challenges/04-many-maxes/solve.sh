#!/usr/bin/env bash
source "$(dirname "$0")/../lib.sh"
cp -R solutions/ch04/. "$REPO/"
restart_worker_hint
