#!/bin/bash
# Cloud sessions only: test deps, the graphify CLI its hooks call, and a fresh code graph.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "$CLAUDE_PROJECT_DIR"

python3 -m pip install -q --root-user-action=ignore -r requirements-dev.txt
command -v graphify >/dev/null || uv tool install -q graphifyy
graphify update . >/dev/null
