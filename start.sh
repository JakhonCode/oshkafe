#!/usr/bin/env bash
# Start the Cozy Café server
# Usage: ./start.sh [port]

set -e
PORT=${1:-8000}

cd "$(dirname "$0")"

# Load .env if it exists
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

# Install deps if needed
if ! python3 -c "import fastapi" 2>/dev/null; then
  echo "Installing dependencies..."
  pip3 install -r requirements.txt
fi

echo ""
echo "  ☕  Cozy Café Server"
echo "  ─────────────────────────────────"
echo "  Customer app: http://localhost:$PORT/"
echo "  Admin panel:  http://localhost:$PORT/admin/"
echo "  API docs:     http://localhost:$PORT/docs"
echo "  ─────────────────────────────────"
echo ""

python -m uvicorn main:app --host 0.0.0.0 --port $PORT
