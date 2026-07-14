# pgdocs-mcp — PostgreSQL 18 + PostGIS docs as an MCP tool

An [MCP](https://modelcontextprotocol.io) server that gives Claude Code (or any
MCP client) fast, local, ranked search over the
[PostgreSQL 18](https://www.postgresql.org/docs/18/index.html) and
[PostGIS 3.5](https://postgis.net/docs/manual-3.5/) manuals. Scrape the official
HTML once, index it locally with TF-IDF + fuzzy + exact matching, expose it over
MCP. **No API keys, no network calls at query time.**

Built by [FloreData](https://floredata.com). Companion code for the write-up
*"Stop Pasting Docs Into Claude. Build a Docs MCP Instead."*

## The four moving parts

| File | Role |
|------|------|
| [`scrape_docs.py`](scrape_docs.py) | BFS-crawls each manual, writes one markdown file per page (`pg__*.md`, `postgis__*.md`). The **only** source-aware part. |
| [`search_index.py`](search_index.py) | Generic TF-IDF + fuzzy + exact search over any directory of markdown. Pickled cache, auto-invalidated on change. |
| [`server.py`](server.py) | FastMCP server exposing `search_docs`, `get_function_signature`, and `pgdocs://` resources. |
| [`setup.sh`](setup.sh) | Installs deps, scrapes, smoke-tests, prints the `claude mcp add` line. |

The boundary between the scraper and everything downstream is the point: the
engine is source-agnostic. Point the `SOURCES` list in `scrape_docs.py` at a
different manual and the rest moves across untouched.

## Quick start

**Prerequisites:** Python 3.10+

```bash
git clone https://github.com/FloreData/pgdocs-mcp
cd pgdocs-mcp
./setup.sh
```

The script installs deps, scrapes both manuals (~5–10 min, resumable), runs a
smoke test, and prints the registration command:

```bash
claude mcp add pgdocs -- python "$(pwd)/server.py"
```

Restart Claude Code and `pgdocs` appears under `/mcp`.

### Manual setup

```bash
pip install -e ".[scrape]"
python scrape_docs.py     # ~5–10 min, resumable
claude mcp add pgdocs -- python "$(pwd)/server.py"
```

## Usage in Claude Code

```text
"Search PostgreSQL docs for window functions"
"What does ST_Intersects return?"          # signature extraction
"Show me pgdocs://docs/pg/sql-select"      # direct resource
"Search PostGIS docs for 'buffer'"
"Search pgdocs for 'index' but only PostgreSQL"   # source='pg'
```

### Search strategies

Default `hybrid` is right for almost everything:

- **`hybrid`** (default): all three combined, exact matches boosted — best for identifiers.
- **`semantic`**: TF-IDF cosine similarity — best for conceptual queries.
- **`fuzzy`**: typo-tolerant matching on titles/filenames.
- **`exact`**: literal substring count.

## Development

```bash
pip install -e ".[dev]"
pytest test_pgdocs.py -v

# Re-scrape (resumable — already-scraped pages are skipped)
python scrape_docs.py

# Force-rebuild one page: delete the file and re-run
rm docs/pg__sql-select.md && python scrape_docs.py
```

## The scraped docs are not in this repo

`scrape_docs.py` downloads the PostgreSQL and PostGIS manuals into `docs/`
(gitignored) and pickles a search index. Those manuals belong to their
respective projects — **regenerate them locally with the scraper** rather than
expecting them in the repo. See [LICENSE](LICENSE): the code is MIT; the
documentation it fetches is not, and remains under its upstream terms.

## License

Code: [MIT](LICENSE). Scraped documentation is not included and remains under
its upstream license.
