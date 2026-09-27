#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Python environment not found. Creating .venv ..."
  python -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

PY=".venv/bin/python"
if ! "$PY" -c "import webview" >/dev/null 2>&1; then
  echo "Missing dependencies. Installing ..."
  "$PY" -m pip install -r requirements.txt
fi

exec "$PY" -m endfieldmodcontroller "$@"
