#!/usr/bin/env bash
# Environment Provisioning for Claude Code Baseline Pipeline

set -euo pipefail

echo "=============================================="
echo " Provisioning Claude Baseline Environment..."
echo "=============================================="

# ==============================================================================
# 1. SYSTEM DEPENDENCIES & AUTHENTICATION
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
else
    echo "✓ Anthropic Claude Code CLI is already installed."
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
# 2. CONDA ENVIRONMENT SETUP
# ==============================================================================
if ! command -v conda &> /dev/null; then
    echo "ERROR: Conda is not installed or not in your PATH." >&2
    exit 1
fi

ENV_NAME="claude-baseline"

if ! conda info --envs | grep -q "^$ENV_NAME "; then
    echo "Creating Conda environment ($ENV_NAME) with Python 3.11..."
    conda create -y -n "$ENV_NAME" python=3.11
    
    echo "Installing base dependencies..."
    conda run -n "$ENV_NAME" pip install --upgrade pip setuptools wheel -q
else
    echo "✓ Conda environment '$ENV_NAME' already exists."
fi

# ALWAYS run this to ensure existing environments don't miss the tracker dependency
echo "Verifying Python dependencies (requests, openai, python-dotenv)..."
conda run -n "$ENV_NAME" pip install requests openai python-dotenv -q

echo "============================================================"
echo " ✓ Environment provisioning complete."
echo "   You may now execute 'run_RQ1_claude.sh'."
echo "============================================================"