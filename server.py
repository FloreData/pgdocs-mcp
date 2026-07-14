#!/usr/bin/env python3
"""
MCP Server for PostgreSQL 18 and PostGIS documentation.

Exposes the scraped docs as resources and provides a hybrid TF-IDF +
fuzzy + exact search tool. Files are namespaced on disk by the source
they came from (`pg__<slug>.md`, `postgis__<slug>.md`) so the same
search index can serve both.
"""

from pathlib import Path
import re
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP


if TYPE_CHECKING:
    from search_index import DocumentSearchIndex


DOCS_DIR = Path(__file__).parent / "docs"

SOURCE_PREFIXES = {
    "pg": "PostgreSQL 18",
    "postgis": "PostGIS",
}

mcp = FastMCP("PostgreSQL + PostGIS Docs")

# Lazy-loaded so the MCP starts instantly; numpy/sklearn imports happen
# on first search request instead of at server boot.
_search_index: "DocumentSearchIndex | None" = None


def get_search_index() -> "DocumentSearchIndex":
    """Get or create the search index instance."""
    global _search_index  # noqa: PLW0603
    if _search_index is None:
        from search_index import DocumentSearchIndex

        _search_index = DocumentSearchIndex(DOCS_DIR)
        _search_index.build_index()
    return _search_index


def _doc_source(name: str) -> str:
    """Return the source prefix ('pg' or 'postgis') for a doc filename stem."""
    for prefix in SOURCE_PREFIXES:
        if name.startswith(f"{prefix}__"):
            return prefix
    return "unknown"


def _doc_slug(name: str) -> str:
    """Strip the source prefix from a doc filename stem."""
    for prefix in SOURCE_PREFIXES:
        marker = f"{prefix}__"
        if name.startswith(marker):
            return name[len(marker):]
    return name


@mcp.resource("pgdocs://docs")
def list_docs() -> str:
    """
    List every scraped doc file, grouped by source (PostgreSQL / PostGIS).
    """
    if not DOCS_DIR.exists():
        return "No docs found. Run 'python scrape_docs.py' first."

    files = sorted(DOCS_DIR.glob("*.md"))
    if not files:
        return "No docs found. Run 'python scrape_docs.py' first."

    grouped: dict[str, list[str]] = {prefix: [] for prefix in SOURCE_PREFIXES}
    other: list[str] = []

    for f in files:
        source = _doc_source(f.stem)
        if source in grouped:
            grouped[source].append(_doc_slug(f.stem))
        else:
            other.append(f.stem)

    output: list[str] = ["# Available PostgreSQL + PostGIS Documentation\n"]
    for prefix, label in SOURCE_PREFIXES.items():
        slugs = grouped[prefix]
        if not slugs:
            continue
        output.append(f"## {label} ({len(slugs)} pages)")
        output.extend(f"- {slug}" for slug in slugs)
        output.append("")

    if other:
        output.append("## Other")
        output.extend(f"- {name}" for name in other)
        output.append("")

    output.append("---")
    output.append("Use: pgdocs://docs/pg/{slug} or pgdocs://docs/postgis/{slug} to read a page.")
    return "\n".join(output)


@mcp.resource("pgdocs://docs/{source}/{slug}")
def get_doc(source: str, slug: str) -> str:
    """
    Get a documentation page.

    Args:
        source: 'pg' (PostgreSQL 18) or 'postgis' (PostGIS)
        slug:   the page slug, e.g. 'select', 'sql-syntax', 'reference'
    """
    if source not in SOURCE_PREFIXES:
        return f"Unknown source '{source}'. Use one of: {list(SOURCE_PREFIXES)}"

    if not DOCS_DIR.exists():
        return "No docs found. Run 'python scrape_docs.py' first."

    path = DOCS_DIR / f"{source}__{slug}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")

    # Fuzzy file match within the same source.
    candidates = list(DOCS_DIR.glob(f"{source}__*{slug}*.md"))
    if len(candidates) == 1:
        return candidates[0].read_text(encoding="utf-8")
    if len(candidates) > 1:
        names = [_doc_slug(c.stem) for c in candidates]
        return f"Multiple matches in {source}: {names}\nPlease be more specific."

    available = [_doc_slug(f.stem) for f in sorted(DOCS_DIR.glob(f"{source}__*.md"))]
    sample = available[:30]
    more = "" if len(available) <= 30 else f"\n...and {len(available) - 30} more."
    return (
        f"Doc not found in {source}: '{slug}'\n\nFirst {len(sample)} available:\n"
        + "\n".join(f"- {a}" for a in sample)
        + more
    )


@mcp.tool()
def search_docs(
    query: str,
    max_results: int = 5,
    strategy: str = "hybrid",
    source: str = "all",
) -> str:
    """
    Search across PostgreSQL 18 and PostGIS documentation.
    Uses TF-IDF ranking with fuzzy matching and exact substring boosting.

    Args:
        query: The search term or phrase (e.g. 'ST_Intersects', 'CREATE INDEX', 'jsonb_path_query')
        max_results: Maximum number of results to return (default: 5)
        strategy: 'hybrid' (default), 'exact', 'fuzzy', or 'semantic'
        source:   'all' (default), 'pg' (PostgreSQL 18 only), or 'postgis' (PostGIS only)
    """
    if not DOCS_DIR.exists():
        return "No docs found. Run 'python scrape_docs.py' first."

    if source not in {"all", *SOURCE_PREFIXES}:
        return f"Unknown source '{source}'. Use one of: all, {', '.join(SOURCE_PREFIXES)}"

    try:
        index = get_search_index()
        results = index.search(query, max_results * 3 if source != "all" else max_results, strategy)
    except Exception as e:
        return f"Search error: {e!s}"

    if source != "all":
        results = [r for r in results if _doc_source(r.doc_name) == source][:max_results]
    else:
        results = results[:max_results]

    if not results:
        scope = "all sources" if source == "all" else SOURCE_PREFIXES[source]
        return f"No results found for '{query}' in {scope}."

    output = [f"# Search results for '{query}'\n"]
    output.append(f"_Strategy: {strategy} | Source: {source}_\n")

    for i, result in enumerate(results, 1):
        src = _doc_source(result.doc_name)
        slug = _doc_slug(result.doc_name)
        label = SOURCE_PREFIXES.get(src, src)
        output.append(f"## {i}. [{label}] {slug}")
        output.append(f"**Relevance**: {result.score:.2f} | **Match type**: {result.match_type}")
        if result.context != "introduction":
            output.append(f"**Section**: {result.context}")
        output.append(f"\n```\n{result.snippet}\n```\n")

    if len(results) == max_results:
        output.append(f"_Showing top {max_results}. Refine your query or try strategy='semantic'._")

    return "\n".join(output)


@mcp.tool()
def get_function_signature(name: str) -> str:
    """
    Look up the signature(s) for a PostgreSQL or PostGIS function/operator.

    Pulls candidate lines that look like function signatures from any doc
    page whose title matches the name. Works well for PostGIS spatial
    functions ('ST_Intersects', 'ST_Buffer') and PG built-ins ('jsonb_path_query').

    Args:
        name: The function or operator name to look up.
    """
    if not DOCS_DIR.exists():
        return "No docs found. Run 'python scrape_docs.py' first."

    needle = name.strip()
    candidates = list(DOCS_DIR.glob(f"*{needle}*.md"))
    if not candidates:
        # Fall back to a content scan — many functions are documented inside
        # a chapter page rather than getting a dedicated file.
        candidates = [p for p in DOCS_DIR.glob("*.md") if needle.lower() in p.read_text(encoding="utf-8").lower()][:5]

    if not candidates:
        return f"No documentation found mentioning '{name}'."

    # PG and PostGIS render signatures with each token on its own line
    # (one HTML tag per identifier). Allow the regex to span those newlines,
    # then normalise whitespace before display so the output is one-liner.
    sig_pattern = re.compile(
        rf"\b{re.escape(needle)}\s*\([^)]*\)(?:\s*(?:→|->|returns)\s*[^\n]+)?",
        re.IGNORECASE | re.DOTALL,
    )

    def _flatten(sig: str) -> str:
        return re.sub(r"\s+", " ", sig).strip()

    output = [f"# Signatures for '{name}'\n"]
    for path in candidates[:5]:
        content = path.read_text(encoding="utf-8")
        signatures = sig_pattern.findall(content)
        if not signatures:
            continue
        slug = _doc_slug(path.stem)
        label = SOURCE_PREFIXES.get(_doc_source(path.stem), "doc")
        output.append(f"## [{label}] {slug}")
        flat = list(dict.fromkeys(_flatten(s) for s in signatures))
        # Real signatures contain type keywords; examples mostly contain literals.
        # Show the type-bearing ones first, cap at 10.
        type_words = ("geometry", "geography", "raster", "jsonb", "jsonpath",
                      "boolean", "integer", "text", "numeric", "setof", "→")
        flat.sort(key=lambda s: 0 if any(w in s for w in type_words) else 1)
        for sig in flat[:10]:
            output.append(f"- `{sig}`")
        output.append("")

    if len(output) == 1:
        return f"Found pages mentioning '{name}' but couldn't extract a signature. Try search_docs('{name}')."

    return "\n".join(output)


@mcp.prompt()
def explain_feature_prompt(feature: str) -> str:
    """Generate a prompt to explain a PostgreSQL or PostGIS feature."""
    return f"""Please explain the PostgreSQL/PostGIS feature '{feature}'.

Use the pgdocs MCP to:
1. Search the docs for '{feature}'
2. Identify which source (PostgreSQL 18 vs PostGIS) is authoritative
3. Summarise: what it does, syntax / signature, typical use cases, pitfalls
4. Give one working SQL example

Quote exact identifiers (function names, options, GUCs) from the docs."""


if __name__ == "__main__":
    mcp.run()
