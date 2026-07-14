#!/bin/bash
# Quick setup script for pgdocs MCP (PostgreSQL 18 + PostGIS)

set -e

echo "🔧 pgdocs MCP Setup"
echo "==================="

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.10+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1-2)
echo "✓ Found Python $PYTHON_VERSION"

echo ""
echo "📦 Installing dependencies..."
pip install -e ".[scrape]" -q

if [ ! -d "docs" ] || [ -z "$(ls -A docs 2>/dev/null)" ]; then
    echo ""
    echo "📚 Scraping PostgreSQL 18 + PostGIS docs (this takes a few minutes)..."
    python scrape_docs.py
else
    echo "✓ Documentation already exists ($(ls docs/*.md 2>/dev/null | wc -l | tr -d ' ') files)"
    echo "  (delete docs/ to force a fresh scrape)"
fi

echo ""
echo "🧪 Testing installation..."
python -c "from search_index import DocumentSearchIndex; from server import mcp; print('✓ All imports successful')"

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Add to Claude Code:"
echo "   claude mcp add pgdocs -- python $(pwd)/server.py"
echo ""
echo "2. Restart Claude Code"
echo ""
echo "3. Test with: /mcp"
