#!/usr/bin/env bash
# End-to-end Claude Code Baseline Pipeline
# Usage: ./run_RQ1_claude.sh [issue_pr_map.json]

set -euo pipefail

# ==============================================================================
# 0. CONFIGURATION & PATHS
# ==============================================================================
echo "=============================================="
echo "Initializing Claude Baseline Environment..."
echo "=============================================="

# Resolve directories based on where the script is located
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ==============================================================================
# 1. ENVIRONMENT VARIABLES & KEYS
# ==============================================================================
if [[ -f ".env" ]]; then
    echo "Loading variables from .env..."
    export $(grep -v '^#' .env | xargs)
else
    echo "ERROR: .env file not found in $CLAUDE_ROOT! Please create one." >&2
    exit 1
fi

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    echo "ERROR: Missing GITHUB_TOKEN in .env" >&2
    exit 1
fi

# Define absolute paths
CLAUDE_ROOT="/home/cc/claude-code-forge/baseline"
CLAUDE_REPOS_ROOT="$CLAUDE_ROOT/repo"
CLAUDE_PIPELINE_SCRIPT="$CLAUDE_ROOT/run_pipeline.py"
STATS_SCRIPT="$REPO_ROOT/stats/entry.py"

cd "$CLAUDE_ROOT"

export ANTHROPIC_API_KEY="${FORGE_API_KEY}"
export ANTHROPIC_BASE_URL="${FORGE_BASE_URL:-https://api.forge.tensorblock.co/v1}"

# ==============================================================================
# 2. SYSTEM DEPENDENCIES & AUTHENTICATION
# ==============================================================================
# Ensure Node/npm is installed
if ! command -v npm &> /dev/null; then
    echo "ERROR: npm is not installed. Please install Node.js/npm first." >&2
    exit 1
fi

# Install Claude Code globally if not present
if ! command -v claude &> /dev/null; then
    echo "Installing Anthropic's Claude Code CLI globally via npm..."
    npm install -g @anthropic-ai/claude-code
fi

# Ensure GitHub CLI is installed
if ! command -v gh &> /dev/null; then
    echo "ERROR: GitHub CLI (gh) is not installed. Please install it first." >&2
    exit 1
fi

# Authenticate GitHub silently
echo "Checking GitHub CLI Authentication..."
gh auth status

# ==============================================================================
# 3. CONDA ENVIRONMENT SETUP
# ==============================================================================
if ! command -v conda &> /dev/null; then
    echo "ERROR: Conda is not installed or not in your PATH." >&2
    exit 1
fi

if ! conda info --envs | grep -q "^claude-baseline "; then
    echo "Creating Conda environment (claude-baseline) with Python 3.11..."
    conda create -y -n claude-baseline python=3.11
    
    echo "Installing base dependencies..."
    conda run -n claude-baseline pip install --upgrade pip setuptools wheel -q
fi

# ALWAYS run this to ensure existing environments don't miss the tracker dependency
conda run -n claude-baseline pip install requests openai dotenv -q

# Determine input map
INPUT_MAP="${1:-issue_pr_map.json}"
if [[ ! -f "$INPUT_MAP" ]]; then
  echo "File not found: $INPUT_MAP" >&2
  exit 1
fi

# Helper to count JSON list length
count_json() { conda run -n claude-baseline python -c "import json; d=json.load(open('$1')); print(len(d) if isinstance(d, (list, dict)) else 0)" 2>/dev/null || echo "0"; }

# ==============================================================================
# 4. INITIALIZE TRACKING & DIRECTORIES
# ==============================================================================
TS="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="runs/${TS}"
OUTPUT_BASE="${RUN_DIR}/results"
LOG_FILE="${RUN_DIR}/claude_pipeline_log.txt"

mkdir -p "$RUN_DIR" "$OUTPUT_BASE"

echo "Input Map: $INPUT_MAP"
echo "Results will be saved to: $OUTPUT_BASE"
echo "All output will be logged to: $LOG_FILE"

# ==============================================================================
# 5. PIPELINE EXECUTION
# ==============================================================================
{
    # echo -e "\n=============================================="
    # echo "Starting cost tracker..."
    # if [[ -f "$STATS_SCRIPT" ]]; then
    #     conda run -n claude-baseline python "$STATS_SCRIPT" start || echo "Warning: Failed to start stats tracker"
    # fi

    # --------------------------------------------------------------------------
    # CLAUDE BASELINE EXECUTION
    # --------------------------------------------------------------------------
    echo -e "\n[1] Running Claude Agent Pipeline..."
    conda run -n claude-baseline python "$CLAUDE_PIPELINE_SCRIPT" \
        --map-file "$INPUT_MAP" \
        --repos-root "$CLAUDE_REPOS_ROOT" \
        --result-root "$OUTPUT_BASE"

    # --------------------------------------------------------------------------
    # RUN F2P FOR EACH BUNDLE
    # --------------------------------------------------------------------------
    echo -e "\n[2] Processing individual F2P bundles..."
    conda run -n claude-baseline bash run_f2p_for_all.sh "$OUTPUT_BASE"

    # ==============================================================================
    # 6. EVALUATION: FAIL-TO-PASS METRICS
    # ==============================================================================
    echo -e "\n[3] Calculating Fail-to-Pass (F2P) Metrics..."
    conda run -n claude-baseline python count_f2p.py
    
    # ==============================================================================
    # 7. END TRACKING & METRICS REPORT
    # ==============================================================================
    # echo -e "\nWaiting 5 seconds for API metrics to sync..."
    # sleep 5
    # echo "Ending cost tracker..."
    # if [[ -f "$STATS_SCRIPT" ]]; then
    #     conda run -n claude-baseline python "$STATS_SCRIPT" end || echo "Warning: Failed to end stats tracker"
    # fi

    echo -e "\n=============================================="
    echo "     CLAUDE PIPELINE FUNNEL REPORT            "
    echo "=============================================="
    echo "1. Input Targets           : $(count_json "$INPUT_MAP") items"
    echo "=============================================="
    echo "Master Log File   : $LOG_FILE"
    echo "Output Bundles    : $OUTPUT_BASE"
    echo "=============================================="

} 2>&1 | tee -a "$LOG_FILE"