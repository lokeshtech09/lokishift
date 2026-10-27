#!/usr/bin/env bash
# LokiShift — one-time setup (macOS / Linux). Run: ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

say "Checking requirements…"
if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv (Python package manager)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
command -v node >/dev/null 2>&1 || fail "Node.js 22+ is required: install it from https://nodejs.org (LTS), then run ./setup.sh again."
node_major=$(node -p 'process.versions.node.split(".")[0]')
[ "$node_major" -ge 22 ] || fail "Node.js $node_major found, 22+ needed: update from https://nodejs.org, then run ./setup.sh again."

say "Installing the backend (Python 3.13 is downloaded automatically if missing)…"
(cd apps/backend && uv sync)

say "Installing and building the frontend…"
(
  cd apps/frontend
  npm install --no-audit --no-fund
  npm run build
  # The build is a self-contained server; give it its static files.
  cp -R .next/static .next/standalone/.next/
  [ -d public ] && cp -R public .next/standalone/
)

chmod +x start.sh
say "Done. Start LokiShift with:  ./start.sh"
