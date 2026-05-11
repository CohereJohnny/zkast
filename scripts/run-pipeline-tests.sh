#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}/apps/pipeline"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install -q -r requirements.txt
export MASTER_ENCRYPTION_KEY="${MASTER_ENCRYPTION_KEY:-$(openssl rand -base64 32)}"
.venv/bin/python -m pytest "$@"
