#!/bin/bash
# Setup for pgdocs MCP (PostgreSQL 18 + PostGIS).
# Creates a project-local virtualenv and does everything inside it —
# it never touches your global/system Python.

set -euo pipefail

# Run from the script's own directory, wherever it's invoked from.
cd "$(dirname "$0")"

echo "🔧 pgdocs MCP Setup"
echo "==================="

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.10+"
    exit 1
fi
echo "✓ Found Python $(python3 --version | cut -d' ' -f2)"

VENV=".venv"
if [ ! -d "$VENV" ]; then
    echo "📦 Creating virtualenv at ./$VENV ..."
    python3 -m venv "$VENV"
fi
PY="$PWD/$VENV/bin/python"

echo ""
echo "📦 Installing dependencies into ./$VENV ..."
"$PY" -m pip install --upgrade pip -q
"$PY" -m pip install -e ".[scrape]" -q

if [ ! -d "docs" ] || [ -z "$(ls -A docs 2>/dev/null)" ]; then
    echo ""
    echo "📚 Scraping PostgreSQL 18 + PostGIS docs (a few minutes; resumable)..."
    "$PY" scrape_docs.py
else
    echo "✓ Documentation already exists ($(ls docs/*.md 2>/dev/null | wc -l | tr -d ' ') files)"
    echo "  (delete docs/ to force a fresh scrape)"
fi

echo ""
echo "🧪 Smoke test..."
"$PY" -c "from search_index import DocumentSearchIndex; from server import mcp; print('✓ imports OK')"

echo ""
echo "✅ Setup complete!"
echo ""
echo "Register with Claude Code (points at the venv's Python, so deps always resolve):"
echo ""
echo "   claude mcp add pgdocs -- \"$PY\" \"$PWD/server.py\""
echo ""
echo "Then restart Claude Code and check /mcp"
