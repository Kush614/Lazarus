#!/usr/bin/env bash
# Starts all six agents and stops them together on Ctrl-C.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs/agents
pids=()
trap 'kill "${pids[@]}" 2>/dev/null || true' EXIT INT TERM
for a in oracle prober sentinel scout scribe digger; do
  uv run python -m "agents.$a.agent" >"logs/agents/$a.log" 2>&1 &
  pids+=("$!")
  echo "started $a (log: logs/agents/$a.log)"
done
wait
