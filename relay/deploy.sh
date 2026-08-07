#!/bin/bash
# ANA Relay — One-Command Deployment
#
# Usage:
#   bash relay/deploy.sh                    # Quick start (dev mode)
#   bash relay/deploy.sh --test             # Run integration tests first
#   bash relay/deploy.sh --prod             # Production mode (gunicorn)
#
# What this does:
#   1. Checks Python and dependencies
#   2. Generates system prompt from codebook
#   3. Starts the ANA relay server
#   4. Opens dashboard URL

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║        ANA Relay — One-Command Deployment               ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Check Python
PYTHON=$(which python3 2>/dev/null || which python 2>/dev/null)
if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3 not found. Install python3 first."
    exit 1
fi
echo "[1/4] Python: $PYTHON"

# Check dependencies
$PYTHON -c "import flask, yaml" 2>/dev/null || {
    echo "[2/4] Installing dependencies..."
    $PYTHON -m pip install flask pyyaml --break-system-packages -q 2>/dev/null || \
    $PYTHON -m pip install flask pyyaml -q
}
echo "[2/4] Dependencies OK"

# Run integration test if requested
if [ "$1" = "--test" ]; then
    echo "[3/4] Running integration tests..."
    $PYTHON "$SCRIPT_DIR/integration_test.py"
    echo ""
fi

# Start server
PORT=${PORT:-6060}
echo "[4/4] Starting ANA Relay on port $PORT..."

if [ "$1" = "--prod" ] || [ "$2" = "--prod" ]; then
    # Production mode with gunicorn
    if command -v gunicorn &>/dev/null; then
        echo "  Production mode (gunicorn with 4 workers)"
        cd "$PROJECT_DIR"
        gunicorn -w 4 -b 0.0.0.0:$PORT relay.server:app
    else
        echo "  gunicorn not found. Install with: pip install gunicorn"
        echo "  Falling back to Flask dev server..."
        $PYTHON "$SCRIPT_DIR/server.py"
    fi
else
    # Dev mode
    echo ""
    echo "  ┌─────────────────────────────────────────────┐"
    echo "  │  ANA Relay is running!                      │"
    echo "  │                                             │"
    echo "  │  Dashboard: http://localhost:$PORT           │"
    echo "  │  Codebook:  http://localhost:$PORT/v1/codebook│"
    echo "  │  Codon API: POST /v1/codon/chat             │"
    echo "  │  Compare:   POST /v1/compare                │"
    echo "  │                                             │"
    echo "  │  Quick test: python3 relay/quick_test.py    │"
    echo "  │  Full test:  python3 relay/integration_test.py│"
    echo "  └─────────────────────────────────────────────┘"
    echo ""
    cd "$PROJECT_DIR"
    $PYTHON "$SCRIPT_DIR/server.py"
fi
