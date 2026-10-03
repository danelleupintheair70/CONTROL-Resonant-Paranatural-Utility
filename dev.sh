#!/usr/bin/env bash
# Doblarr local dev helper (Linux / macOS / Git Bash)
#
#   ./dev.sh setup          install Python + Node deps
#   ./dev.sh serve          build the web UI, run it + the API (http://127.0.0.1:6363)
#   ./dev.sh ui             web UI dev server with live reload (http://127.0.0.1:5363)
#   ./dev.sh validate       the fast checks once: ruff, mypy, eslint, node tests, UI build,
#                           pytest without the slow end-to-end tests (watching: dev.ps1)
#   ./dev.sh test           Python tests, in parallel (pytest -n auto)
#   ./dev.sh test-web       frontend unit tests (node --test)
#   ./dev.sh test-browser   Playwright browser tests (builds the UI first)
#   ./dev.sh lint           ruff + mypy + eslint
#   ./dev.sh check          everything CI runs (minus docker build)
#   ./dev.sh cli <args...>  pass through to the doblarr CLI
#
# Examples:
#   ./dev.sh cli check
#   ./dev.sh cli dub movie.mkv --to es --dry-run

set -euo pipefail
cd "$(dirname "$0")"

# Prefer the project venv if it exists, else fall back to system python.
# Windows venvs use Scripts/, POSIX venvs use bin/.
if [ -x .venv/Scripts/python.exe ]; then
    PYTHON=.venv/Scripts/python.exe
elif [ -x .venv/bin/python ]; then
    PYTHON=.venv/bin/python
else
    PYTHON=python
fi

step() {
    printf '\n==> %s\n' "$1"
    shift
    "$@"
}

cmd="${1:-help}"
[ $# -gt 0 ] && shift

case "$cmd" in
    setup)
        step "pip install -e .[dev]" "$PYTHON" -m pip install -e ".[dev]"
        step "npm ci" npm ci
        step "playwright install chromium" npx playwright install chromium
        ;;
    serve)
        step "build web UI" npm run build:ui
        exec "$PYTHON" -m doblarr serve "$@"
        ;;
    ui)
        exec npm run dev:ui
        ;;
    test)
        exec "$PYTHON" -m pytest -q -n auto "$@"
        ;;
    test-web)
        exec npm test
        ;;
    test-browser)
        exec npm run test:browser -- "$@"
        ;;
    validate)
        step "ruff" "$PYTHON" -m ruff check .
        step "mypy" "$PYTHON" -m mypy doblarr/
        step "eslint" npm run lint
        step "node tests" npm test
        step "ui build" npm run build:ui
        step "pytest (fast tier)" "$PYTHON" -m pytest -q -n auto -m "not slow"
        printf '
All fast checks passed.
'
        ;;
    lint)
        step "ruff" "$PYTHON" -m ruff check .
        step "mypy" "$PYTHON" -m mypy doblarr/
        step "eslint" npm run lint
        ;;
    check)
        step "ruff" "$PYTHON" -m ruff check .
        step "mypy" "$PYTHON" -m mypy doblarr/
        step "pytest" "$PYTHON" -m pytest -q -n auto --cov=doblarr --cov-report=term-missing --cov-fail-under=70
        step "npm run check" npm run check
        printf '\nAll checks passed.\n'
        ;;
    cli)
        exec "$PYTHON" -m doblarr "$@"
        ;;
    *)
        sed -n '2,16p' "$0"
        ;;
esac
