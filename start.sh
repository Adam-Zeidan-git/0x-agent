#!/usr/bin/env bash
# One command for Linux/Mac: creates the environment on first run, then opens the 0x web interface.
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python) || { echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1; }
[ -d .venv ] || { echo "First run: installing (about a minute)..."; "$PY" -m venv .venv; }
. .venv/bin/activate
python -c "import autoclose_ui" 2>/dev/null || pip install -q -e .
exec python -m autoclose_ui --open "$@"
