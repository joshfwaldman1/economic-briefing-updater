#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
RUNTIME_NODE="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
RUNTIME_PYTHON="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [[ ! -x "$RUNTIME_NODE" ]]; then RUNTIME_NODE="$(command -v node || true)"; fi
if [[ ! -x "$RUNTIME_PYTHON" ]]; then RUNTIME_PYTHON="$(command -v python3 || true)"; fi
if [[ -z "$RUNTIME_NODE" || -z "$RUNTIME_PYTHON" ]]; then echo 'Node.js 20+ and Python 3 are required.'; exit 1; fi
RUN_FOLDER="runs/$(date +%Y-%m-%d_%H-%M-%S)-$$"
mkdir -p "$RUN_FOLDER"
"$RUNTIME_NODE" update_workbook.mjs --output "$RUN_FOLDER/Gene Master Prep Updated.xlsx"
"$RUNTIME_PYTHON" update_chartbook.py --output-dir "$RUN_FOLDER/chartbook"
"$RUNTIME_PYTHON" download_fred_charts.py --output-dir "$RUN_FOLDER/fred_charts"
echo "Finished. Updated files are in $RUN_FOLDER"

