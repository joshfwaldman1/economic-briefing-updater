#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
RUNTIME_PYTHON="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [[ ! -x "$RUNTIME_PYTHON" ]]; then RUNTIME_PYTHON="$(command -v python3 || true)"; fi
if [[ -z "$RUNTIME_PYTHON" ]]; then echo 'Python 3 is required.'; exit 1; fi
"$RUNTIME_PYTHON" update_chartbook.py --output-dir "runs/chartbook-$(date +%Y-%m-%d_%H-%M-%S)-$$" "$@"

