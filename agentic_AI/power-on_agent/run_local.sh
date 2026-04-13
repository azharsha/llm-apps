#!/usr/bin/env bash
# Usage: ./run_local.sh [host] [ssh-user] [dts-path]
# Defaults to localhost if no arguments given.
set -e

HOST="${1:-127.0.0.1}"
SSH_USER="${2:-azhar}"
DTS="${3:-poagent/board/dts/sample_tgl.dts}"

echo "Target: ${SSH_USER}@${HOST}  DTS: ${DTS}"

python3 -m poagent \
  --host "${HOST}" \
  --ssh-user "${SSH_USER}" \
  --ssh-key ~/.ssh/id_rsa \
  --dts "${DTS}" \
  --board-name "$(echo "${HOST}" | tr '.' '-')" \
  --subsystem sensors_misc \
  --subsystem networking \
  --watchdog-keepalive disable \
  --confirm-overlay pre_validated \
  --output-dir /tmp/poagent-runs \
  --log-level INFO \
  --agent-timeout 300
