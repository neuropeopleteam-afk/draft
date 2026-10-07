#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/backend"
flock /tmp/spectrek_heavy.lock /home/user/workspace/spectrek/.venv/bin/python -m pytest -q -p no:cacheprovider > "$ROOT/docs/realdata/full_pytest.log" 2>&1
PYTEST_STATUS=$?
cd "$ROOT/frontend"
flock /tmp/spectrek_heavy.lock npm run build > "$ROOT/docs/realdata/frontend_build.log" 2>&1
BUILD_STATUS=$?
printf '{"pytest_exit":%s,"build_exit":%s}\n' "$PYTEST_STATUS" "$BUILD_STATUS" > "$ROOT/docs/realdata/checks_status.json"
