#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

echo "======================================================"
echo "  Heat Environment Platform - Environment Setup"
echo "======================================================"

# 1. Check Python & Node
command -v python3 >/dev/null 2>&1 || { echo "Python 3 is required but not installed."; exit 1; }
command -v node >/dev/null 2>&1 || { echo "Node.js is required but not installed."; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm is required but not installed."; exit 1; }

# 2. Virtualenv
VENV_DIR="$ROOT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtualenv at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi
VENV_PY="$VENV_DIR/bin/python"

echo "Installing backend dependencies..."
"$VENV_PY" -m pip install --upgrade pip -q
"$VENV_PY" -m pip install -r "$BACKEND_DIR/requirements.txt"

# 3. Frontend npm
echo "Installing frontend dependencies..."
cd "$FRONTEND_DIR"
npm install
cd "$ROOT_DIR"

# 4. Config files
if [ ! -f "$BACKEND_DIR/.env" ] && [ -f "$BACKEND_DIR/.env.example" ]; then
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    echo "Created backend/.env from .env.example"
fi

if [ ! -f "$FRONTEND_DIR/.env" ] && [ -f "$FRONTEND_DIR/.env.example" ]; then
    cp "$FRONTEND_DIR/.env.example" "$FRONTEND_DIR/.env"
    echo "Created frontend/.env from .env.example"
fi

echo "======================================================"
echo "  Environment setup finished successfully!"
echo "  To initialize database: $VENV_PY scripts/init_database.py"
echo "======================================================"
