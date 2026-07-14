#!/usr/bin/env python3
"""
Tests for pgdocs-mcp specifics: source-prefixed filenames, source-filtered
search, signature extraction.
"""

import pytest

import server
from search_index import DocumentSearchIndex


@pytest.fixture
def pgdocs_dir(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()

    (docs / "pg__select.md").write_text(
        "# SELECT\n\nSource: https://www.postgresql.org/docs/18/sql-select.html\n\n"
        "SELECT retrieves rows from zero or more tables.\n\n"
        "## Synopsis\n\n"
        "SELECT [ ALL | DISTINCT [ ON ( expression [, ...] ) ] ]\n"
        "    [ * | expression [ [ AS ] output_name ] [, ...] ]\n"
    )
    (docs / "pg__jsonb.md").write_text(
        "# JSON Functions and Operators\n\n"
        "Source: https://www.postgresql.org/docs/18/functions-json.html\n\n"
        "jsonb_path_query ( target jsonb, path jsonpath ) → setof jsonb\n"
        "Returns all JSON items matched by the JSON path expression.\n"
    )
    (docs / "postgis__st_intersects.md").write_text(
        "# ST_Intersects\n\n"
        "Source: https://postgis.net/docs/manual-3.5/ST_Intersects.html\n\n"
        "ST_Intersects ( geometry A, geometry B ) → boolean\n"
        "Returns true if two geometries spatially intersect.\n"
    )

    # Point the server at the temp docs dir for resource/tool calls.
    monkeypatch.setattr(server, "DOCS_DIR", docs)
    monkeypatch.setattr(server, "_search_index", None)
    return docs


def test_list_docs_groups_by_source(pgdocs_dir):
    output = server.list_docs()
    assert "PostgreSQL 18 (2 pages)" in output
    assert "PostGIS (1 pages)" in output
    assert "- select" in output
    assert "- st_intersects" in output
    # Source prefixes should be stripped from the user-facing list.
    assert "pg__select" not in output


def test_get_doc_by_source(pgdocs_dir):
    content = server.get_doc("pg", "select")
    assert "SELECT retrieves rows" in content

    content = server.get_doc("postgis", "st_intersects")
    assert "spatially intersect" in content


def test_get_doc_unknown_source(pgdocs_dir):
    out = server.get_doc("mysql", "select")
    assert "Unknown source" in out


def test_search_filters_by_source(pgdocs_dir):
    pg_only = server.search_docs("intersect", source="pg")
    postgis_only = server.search_docs("intersect", source="postgis")

    # PG docs don't mention 'intersect' in this fixture.
    assert "No results" in pg_only or "st_intersects" not in pg_only.lower()
    assert "st_intersects" in postgis_only.lower()


def test_search_all_sources_default(pgdocs_dir):
    out = server.search_docs("SELECT")
    assert "select" in out.lower()


def test_get_function_signature_postgis(pgdocs_dir):
    out = server.get_function_signature("ST_Intersects")
    assert "ST_Intersects" in out
    assert "boolean" in out


def test_get_function_signature_pg_builtin(pgdocs_dir):
    out = server.get_function_signature("jsonb_path_query")
    assert "jsonb_path_query" in out


def test_search_index_handles_mixed_corpus(pgdocs_dir):
    index = DocumentSearchIndex(pgdocs_dir)
    index.build_index()

    assert len(index.documents) == 3
    names = {d.name for d in index.documents}
    assert "pg__select" in names
    assert "postgis__st_intersects" in names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
