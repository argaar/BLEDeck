#!/usr/bin/env bash
# Developer setup for BLEDeck Windows app (cross-platform variant).
# Installs runtime + test + build dependencies into the active environment.
# Usage: from inside an activated venv, run ./setup-dev.sh
set -euo pipefail

cd "$(dirname "$0")"

echo "Installing runtime dependencies..."
python -m pip install -r requirements.txt

echo
echo "Installing development dependencies (pytest, etc.)..."
python -m pip install -r requirements-dev.txt

echo
echo "Installing build dependencies (PyInstaller)..."
python -m pip install -r requirements-build.txt

echo
echo "Verifying setup by running the test suite..."
python -m pytest tests/ -q

echo
echo "Setup complete. Run the app with: python main.py    or build with: build.bat (Windows only)"
