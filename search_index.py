#!/usr/bin/env python3
"""
Advanced text search using TF-IDF inverted index and fuzzy matching.
Provides fast, ranked search results with typo tolerance.

This module is intentionally generic: it works on any directory of
markdown files, so the same engine can be pointed at a different docs
corpus by swapping only the scraper.
"""

from dataclasses import dataclass
from pathlib import Path
import pickle
import re

import numpy as np
from rapidfuzz import fuzz, process
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class SearchResult:
    """A single search result with relevance score."""

    doc_name: str
    score: float
    snippet: str
    context: str
    match_type: str  # 'exact', 'fuzzy', or 'semantic'


@dataclass
class Document:
    """Parsed document with structured content."""

    name: str
    path: Path
    title: str
    content: str
    sections: dict[str, str]  # section_heading -> section_text


class DocumentSearchIndex:
    """
    Fast document search using TF-IDF vectorization and fuzzy matching.

    Features:
    - TF-IDF based semantic search with cosine similarity
    - Fuzzy string matching for typo tolerance
    - Caching to avoid rebuilding index
    - Section-aware snippet extraction
    - Relevance scoring combining multiple signals
    """

    def __init__(self, docs_dir: Path, cache_file: Path | None = None):
        self.docs_dir = docs_dir
        self.cache_file = cache_file or (docs_dir.parent / ".search_cache.pkl")

        self.documents: list[Document] = []
        self.vectorizer: TfidfVectorizer | None = None
        self.tfidf_matrix = None
        self._index_mtime: float | None = None

    def _needs_rebuild(self) -> bool:
        """Check if index needs to be rebuilt."""
        if not self.documents or self.tfidf_matrix is None:
            return True

        if self._index_mtime:
            for doc_path in self.docs_dir.glob("*.md"):
                if doc_path.stat().st_mtime > self._index_mtime:
                    return True
        return False

    def _parse_document(self, path: Path) -> Document:
        """Parse a markdown document into structured sections."""
        content = path.read_text(encoding="utf-8")
        lines = content.split("\n")

        title = path.stem
        for line in lines[:10]:
            if line.startswith("# "):
                title = line[2:].strip()
                break

        sections: dict[str, str] = {}
        current_section = "introduction"
        current_text: list[str] = []

        for line in lines:
            if line.startswith("#"):
                if current_text:
                    sections[current_section] = "\n".join(current_text).strip()
                current_section = re.sub(r"^#+\s*", "", line).strip().lower()
                current_text = []
            else:
                current_text.append(line)

        if current_text:
            sections[current_section] = "\n".join(current_text).strip()

        return Document(name=path.stem, path=path, title=title, content=content, sections=sections)

    def build_index(self, force: bool = False) -> None:
        """Build or load the search index."""
        if not force and self.cache_file.exists():
            try:
                with open(self.cache_file, "rb") as f:
                    cache = pickle.load(f)  # nosec B301 - loading our own cache file
                    self.documents = cache["documents"]
                    self.vectorizer = cache["vectorizer"]
                    self.tfidf_matrix = cache["tfidf_matrix"]
                    self._index_mtime = cache["mtime"]

                if not self._needs_rebuild():
                    return
            except Exception:
                pass

        self.documents = []
        for path in sorted(self.docs_dir.glob("*.md")):
            self.documents.append(self._parse_document(path))

        if not self.documents:
            return

        corpus = [doc.content for doc in self.documents]
        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1,
            max_df=0.8,
        )
        self.tfidf_matrix = self.vectorizer.fit_transform(corpus)
        self._index_mtime = max(doc.path.stat().st_mtime for doc in self.documents)

        try:
            with open(self.cache_file, "wb") as f:
                pickle.dump(
                    {
                        "documents": self.documents,
                        "vectorizer": self.vectorizer,
                        "tfidf_matrix": self.tfidf_matrix,
                        "mtime": self._index_mtime,
                    },
                    f,
                )
        except Exception as e:
            print(f"Warning: Could not save search cache: {e}")

    def _extract_snippet(self, doc: Document, query: str, context_lines: int = 2) -> tuple[str, str]:
        """
        Extract relevant snippet with context around the query match.
        Returns (snippet, context) where context is the section name.
        """
        query_lower = query.lower()
        lines = doc.content.split("\n")

        best_idx = -1
        best_score = 0

        for i, line in enumerate(lines):
            if not line.strip():
                continue
            score = fuzz.partial_ratio(query_lower, line.lower())
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx == -1:
            snippet_lines = [line for line in lines[:5] if line.strip()][:3]
            return "\n".join(snippet_lines), "introduction"

        start = max(0, best_idx - context_lines)
        end = min(len(lines), best_idx + context_lines + 1)
        snippet = "\n".join(lines[start:end])

        context = "introduction"
        for section_name in doc.sections:
            section_text = doc.sections[section_name]
            if lines[best_idx] in section_text:
                context = section_name
                break

        return snippet.strip(), context

    def search_tfidf(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """Search using TF-IDF cosine similarity."""
        if not self.documents or self.tfidf_matrix is None:
            return []

        query_vec = self.vectorizer.transform([query])
        similarities = cosine_similarity(query_vec, self.tfidf_matrix).flatten()
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for idx in top_indices:
            score = similarities[idx]
            if score < 0.05:
                continue

            doc = self.documents[idx]
            snippet, context = self._extract_snippet(doc, query)

            results.append(
                SearchResult(
                    doc_name=doc.name, score=float(score), snippet=snippet, context=context, match_type="semantic"
                )
            )

        return results

    def search_fuzzy(self, query: str, top_k: int = 10, threshold: int = 60) -> list[SearchResult]:
        """Search using fuzzy string matching on document names and titles."""
        if not self.documents:
            return []

        candidates = [(doc.name, doc) for doc in self.documents]
        candidates.extend([(doc.title, doc) for doc in self.documents])

        matches = process.extract(
            query,
            [c[0] for c in candidates],
            scorer=fuzz.WRatio,
            limit=top_k * 2,
        )

        results = []
        seen_docs = set()

        for _match_text, score, idx in matches:
            if score < threshold:
                continue

            doc = candidates[idx][1]
            if doc.name in seen_docs:
                continue
            seen_docs.add(doc.name)

            snippet, context = self._extract_snippet(doc, query)

            results.append(
                SearchResult(
                    doc_name=doc.name,
                    score=score / 100.0,
                    snippet=snippet,
                    context=context,
                    match_type="fuzzy",
                )
            )

            if len(results) >= top_k:
                break

        return results

    def search_exact(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """Search for exact substring matches."""
        if not self.documents:
            return []

        query_lower = query.lower()
        results = []

        for doc in self.documents:
            content_lower = doc.content.lower()
            count = content_lower.count(query_lower)
            if count == 0:
                continue

            score = min(1.0, count / 10.0)
            snippet, context = self._extract_snippet(doc, query)

            results.append(
                SearchResult(doc_name=doc.name, score=score, snippet=snippet, context=context, match_type="exact")
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def search(self, query: str, max_results: int = 5, strategy: str = "hybrid") -> list[SearchResult]:
        """
        Unified search combining multiple strategies.

        Args:
            query: Search query
            max_results: Maximum number of results to return
            strategy: 'exact', 'fuzzy', 'semantic', or 'hybrid'

        Returns:
            List of SearchResult objects, sorted by relevance
        """
        if self._needs_rebuild():
            self.build_index()

        if not self.documents:
            return []

        all_results = []

        if strategy in ("exact", "hybrid"):
            exact_results = self.search_exact(query, max_results)
            for r in exact_results:
                r.score *= 1.5
            all_results.extend(exact_results)

        if strategy in ("fuzzy", "hybrid"):
            fuzzy_results = self.search_fuzzy(query, max_results)
            for r in fuzzy_results:
                r.score *= 1.2
            all_results.extend(fuzzy_results)

        if strategy in ("semantic", "hybrid"):
            semantic_results = self.search_tfidf(query, max_results)
            all_results.extend(semantic_results)

        result_map: dict[str, SearchResult] = {}
        for result in all_results:
            if result.doc_name in result_map:
                existing = result_map[result.doc_name]
                if result.score > existing.score:
                    result.match_type = f"{existing.match_type}+{result.match_type}"
                    result_map[result.doc_name] = result
            else:
                result_map[result.doc_name] = result

        final_results = sorted(result_map.values(), key=lambda r: r.score, reverse=True)
        return final_results[:max_results]

    def get_document(self, name: str) -> Document | None:
        """Get a document by name."""
        for doc in self.documents:
            if doc.name == name:
                return doc
        return None
