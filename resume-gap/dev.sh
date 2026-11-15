#!/usr/bin/env bash
# Start the API (port 8000) and the frontend (port 5173) together. Ctrl+C stops both.
#   ./dev.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x backend/.venv/bin/uvicorn ]; then
  echo "Backend isn't set up yet. Run:"
  echo "  cd backend && python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
if [ ! -d frontend/node_modules ]; then
  echo "Installing frontend dependencies..."
  (cd frontend && npm install)
fi

# On exit (Ctrl+C, or either server crashing), stop every process this script started.
trap 'trap - EXIT; kill 0 2>/dev/null' INT TERM EXIT

(cd backend && exec .venv/bin/uvicorn app.main:app --reload --port 8000) &
(cd frontend && exec npm run dev -- --port 5173 --strictPort) &

echo ""
echo "  App:  http://localhost:5173"
echo "  API:  http://localhost:8000/docs"
echo "  Ctrl+C to stop both."
echo ""

# If either server exits, stop the other too instead of leaving it running alone.
wait -n 2>/dev/null || wait
