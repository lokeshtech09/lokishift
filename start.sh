#!/usr/bin/env bash
# LokiShift — start the app (macOS / Linux). Run: ./start.sh   (Ctrl+C stops it)
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

[ -d apps/backend/.venv ] && [ -f apps/frontend/.next/standalone/server.js ] || { echo "Run ./setup.sh first."; exit 1; }

for port in 8000 3000; do
  if curl -s --max-time 2 -o /dev/null "http://127.0.0.1:$port"; then
    echo "Port $port is already in use (is LokiShift already running in another window?). Stop that first."
    exit 1
  fi
done

(cd apps/backend && exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8000) &
backend=$!
(cd apps/frontend/.next/standalone && HOSTNAME=127.0.0.1 PORT=3000 exec node server.js) &
frontend=$!
trap 'kill $backend $frontend 2>/dev/null; wait 2>/dev/null; echo; echo "LokiShift stopped."' INT TERM EXIT

echo "Starting LokiShift…"
for _ in $(seq 1 90); do
  curl -fs http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1 &&
    curl -fs http://127.0.0.1:3000 >/dev/null 2>&1 && break
  sleep 1
done
printf '\n\033[1mLokiShift is running: http://localhost:3000\033[0m  (Ctrl+C to stop)\n\n'
case "$(uname)" in
  Darwin) open http://localhost:3000 ;;
  Linux)  command -v xdg-open >/dev/null 2>&1 && xdg-open http://localhost:3000 >/dev/null 2>&1 || true ;;
esac
wait
