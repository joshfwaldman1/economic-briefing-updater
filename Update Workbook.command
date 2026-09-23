#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
RUNTIME_NODE="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if [[ ! -x "$RUNTIME_NODE" ]]; then RUNTIME_NODE="$(command -v node || true)"; fi
if [[ -z "$RUNTIME_NODE" ]]; then echo 'Node.js 20+ is required.'; exit 1; fi
"$RUNTIME_NODE" update_workbook.mjs "$@"
echo 'Finished. New files are in the runs folder.'

