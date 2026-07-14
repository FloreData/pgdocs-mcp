#!/usr/bin/env python3
"""
One-time scraper for PostgreSQL 18 and PostGIS documentation.

Both doc sites publish a table of contents we can crawl, so we discover
URLs from the index pages instead of hardcoding hundreds of paths. Run
this to populate the docs/ directory, then re-run when docs update.
"""

from collections import deque
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx


DOCS_DIR = Path(__file__).parent / "docs"


# Each source has:
#   prefix:    filename prefix to keep PG and PostGIS docs separate on disk
#   index:     entry point that lists every page
#   base:      URL prefix; anything outside this is ignored
#   allowed:   regex a candidate URL must match to be queued
SOURCES: list[dict[str, str]] = [
    {
        "prefix": "pg",
        "index": "https://www.postgresql.org/docs/18/index.html",
        "base": "https://www.postgresql.org/docs/18/",
        "allowed": r"^https://www\.postgresql\.org/docs/18/[A-Za-z0-9_\-]+\.html$",
    },
    {
        "prefix": "postgis",
        "index": "https://postgis.net/docs/manual-3.5/",
        "base": "https://postgis.net/docs/manual-3.5/",
        "allowed": r"^https://postgis\.net/docs/manual-3\.5/[A-Za-z0-9_\-\.]+\.html$",
    },
]


REQUEST_DELAY_SECONDS = 0.3
USER_AGENT = "pgdocs-mcp/0.1 (+https://github.com/FloreData/pgdocs-mcp)"

# Safety cap: stop discovery if a source explodes beyond this many pages.
MAX_PAGES_PER_SOURCE = 1500


def clean_text(text: str) -> str:
    """Collapse the worst whitespace artefacts from HTML extraction."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def extract_main_content(soup: BeautifulSoup) -> tuple[str, str]:
    """
    Return (title, text) for a doc page.

    Both PG and PostGIS use a `div.sect1` / `div.refentry` style derived
    from DocBook XSL. We pick the densest text block and strip nav chrome.
    """
    title_el = soup.find("h1") or soup.find("title")
    title = title_el.get_text(strip=True) if title_el else "untitled"

    candidates = [
        soup.find("div", class_="sect1"),
        soup.find("div", class_="refentry"),
        soup.find("div", class_="book"),
        soup.find("article"),
        soup.find("main"),
        soup.find("div", id="docContent"),
        soup.find("body"),
    ]
    content = next((c for c in candidates if c is not None), None)
    if content is None:
        return title, ""

    for tag in content.find_all(["nav", "script", "style", "footer", "header"]):
        tag.decompose()

    # Navigation tables at the top of every PG page have class "navheader" /
    # "navfooter" — strip them so search snippets stay relevant.
    for tag in content.find_all("table", class_=["navheader", "navfooter"]):
        tag.decompose()

    return title, clean_text(content.get_text(separator="\n", strip=True))


def url_to_filename(url: str, prefix: str) -> str:
    """`https://.../docs/18/select.html` -> `pg__select.md`."""
    slug = urlparse(url).path.rsplit("/", 1)[-1]
    slug = slug.removesuffix(".html") or "index"
    slug = re.sub(r"[^A-Za-z0-9_\-\.]", "_", slug)
    return f"{prefix}__{slug}.md"


def scrape_source(client: httpx.Client, source: dict[str, str]) -> tuple[int, list[str]]:
    """
    BFS-crawl one source: fetch each page once, write its markdown, and
    queue any further allowed links found on the same page. PG and PostGIS
    link their leaf pages (`sql-select.html`, `ST_Intersects.html`) from
    chapter pages rather than from the root index, so single-level
    discovery isn't enough.

    Returns (success_count, failed_urls).
    """
    print(f"\n=== {source['prefix']} ({source['index']}) ===")
    allowed = re.compile(source["allowed"])
    base = source["base"]
    prefix = source["prefix"]

    seen: set[str] = set()
    queue: deque[str] = deque([source["index"]])
    success = 0
    failed: list[str] = []

    while queue:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)

        is_index = url == source["index"]
        filename = None if is_index else url_to_filename(url, prefix)
        out_path = None if filename is None else DOCS_DIR / filename
        already_have = out_path is not None and out_path.exists() and out_path.stat().st_size > 0

        try:
            resp = client.get(url, follow_redirects=True, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"  FAIL {url} ({e})")
            failed.append(url)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        if not is_index:
            if not already_have:
                title, content = extract_main_content(soup)
                md = f"# {title}\n\nSource: {url}\n\n---\n\n{content}\n"
                out_path.write_text(md, encoding="utf-8")
            success += 1
            if success % 25 == 0:
                print(f"  {prefix}: {success} pages written ({len(queue)} queued)...")

        # Queue any further allowed links found on this page.
        for a in soup.find_all("a", href=True):
            full = urljoin(base, a["href"]).split("#", 1)[0]
            if allowed.match(full) and full not in seen:
                queue.append(full)

        if len(seen) >= MAX_PAGES_PER_SOURCE:
            print(f"  hit safety cap of {MAX_PAGES_PER_SOURCE} pages; stopping.")
            break

        # Skip the polite delay when we served from cache — no network used.
        if not already_have:
            time.sleep(REQUEST_DELAY_SECONDS)

    return success, failed


def main() -> None:
    DOCS_DIR.mkdir(exist_ok=True)

    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers) as client:
        for source in SOURCES:
            success, failed = scrape_source(client, source)
            print(f"  -> {success} ok, {len(failed)} failed")
            if failed:
                for u in failed:
                    print(f"     - {u}")

    total = len(list(DOCS_DIR.glob("*.md")))
    print(f"\nDone. {total} docs on disk at {DOCS_DIR}.")


if __name__ == "__main__":
    main()
