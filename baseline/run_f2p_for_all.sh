#!/bin/bash
# Script to run f2p_from_swegent_bundle.py for all agent_name/id combinations in the results folder

RESULTS_DIR="${1:-}"
SCRIPT="/home/cc/claude-code-forge/baseline/f2p_from_swegent_bundle.py"

for agent_name in "$RESULTS_DIR"/*; do
  [ -d "$agent_name" ] || continue
  for id in "$agent_name"/*; do
    [ -d "$id" ] || continue
    echo "Running for $id..."
    python "$SCRIPT" "$id"
  done
done
