#!/usr/bin/env python3
"""search-fulltext.py — TF-IDF term-frequency search for wiki pages.

Usage:
    python3 search-fulltext.py <pages_dir> <query> [--top N] [--json]

Builds an in-memory TF-IDF index from all .md files and returns ranked results.
Provides comprehensive full-text search across all pages.
"""

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

from wiki_logging import get_logger
from exceptions import SearchError

logger = get_logger(__name__)


class WikiSearcher:
    """Full-text TF-IDF search for wiki pages."""

    STOP_WORDS = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "and",
        "or",
        "but",
        "not",
        "this",
        "that",
        "it",
        "by",
        "from",
        "as",
        "be",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "must",
        "about",
        "after",
        "before",
        "between",
        "into",
        "through",
        "during",
        "without",
        "also",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "than",
        "too",
        "very",
        "just",
        "only",
        "own",
        "same",
        "so",
        "then",
        "these",
        "those",
        "there",
        "here",
        "where",
        "when",
        "how",
        "what",
        "which",
        "who",
        "why",
    }

    def __init__(self, pages_dir: str):
        self.pages_dir = Path(pages_dir)
        self.documents = {}  # {slug: content}
        self.titles = {}  # {slug: title}
        self.term_freq = {}  # {slug: {term: freq}}
        self.doc_freq = {}  # {term: count}
        self._index_pages()

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text: lowercase, split on non-alphanumeric, remove stopwords."""
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return [t for t in tokens if t not in self.STOP_WORDS and len(t) > 1]

    def _extract_title(self, content: str) -> str:
        """Extract title from frontmatter or first heading."""
        # Try frontmatter
        match = re.search(r"^---\s*\ntitle:\s*([^\n]+)", content, re.MULTILINE)
        if match:
            return match.group(1).strip()

        # Try first H1
        match = re.search(r"^#\s+([^\n]+)", content, re.MULTILINE)
        if match:
            return match.group(1).strip()

        return ""

    def _index_pages(self):
        """Build TF-IDF index from all .md files."""
        # Collect all documents and tokens
        all_tokens = Counter()

        for md_file in self.pages_dir.glob("**/*.md"):
            slug = md_file.stem
            try:
                content = md_file.read_text(encoding="utf-8")
                self.documents[slug] = content
                self.titles[slug] = self._extract_title(content)

                # Tokenize and count
                tokens = self._tokenize(content)
                token_counts = Counter(tokens)
                self.term_freq[slug] = token_counts

                # Track document frequency
                for term in set(tokens):
                    self.doc_freq[term] = self.doc_freq.get(term, 0) + 1
                    all_tokens[term] += 1

            except Exception as e:
                logger.error(f"Error indexing {slug}: {e}")

    def _calculate_tfidf(self, query_terms: list[str], slug: str) -> float:
        """Calculate TF-IDF score for document."""
        if slug not in self.term_freq:
            return 0.0

        token_counts = self.term_freq[slug]
        total_terms = sum(token_counts.values()) or 1
        score = 0.0

        for term in query_terms:
            if term in token_counts:
                tf = token_counts[term] / total_terms
                idf = math.log(len(self.documents) / (self.doc_freq.get(term, 1) + 1))
                score += tf * idf

        return score

    def _apply_boosts(self, score: float, query_terms: list[str], slug: str) -> float:
        """Apply content-aware boosts."""
        content = self.documents.get(slug, "")
        title = self.titles.get(slug, "")

        # Boost for title match
        for term in query_terms:
            if term in title.lower():
                score += 0.5

        # Boost for first paragraph match
        first_para_match = 0
        first_para = re.split(r"\n\n", content)[0]
        for term in query_terms:
            if term in first_para.lower():
                first_para_match += 1

        score += first_para_match * 0.3

        return score

    def _extract_snippet(self, content: str, query_terms: list[str]) -> str:
        """Extract 150-char snippet containing highest-scoring term."""
        sentences = re.split(r"[.!?]+", content)

        best_sentence = ""
        best_score = 0

        for sentence in sentences:
            score = 0
            for term in query_terms:
                if term in sentence.lower():
                    score += 1

            if score > best_score:
                best_score = score
                best_sentence = sentence.strip()

        if best_sentence:
            return best_sentence[:150]
        return content[:150]

    def search(self, query: str, top: int = 10) -> list[dict]:
        """Search and return ranked results."""
        query_terms = self._tokenize(query)

        if not query_terms:
            return []

        # Score all documents
        scores = {}
        for slug in self.documents:
            tfidf = self._calculate_tfidf(query_terms, slug)
            scores[slug] = self._apply_boosts(tfidf, query_terms, slug)

        # Sort and return top results
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top]

        results = []
        for rank, (slug, score) in enumerate(ranked, 1):
            if score > 0:
                content = self.documents[slug]
                title = self.titles[slug] or slug
                snippet = self._extract_snippet(content, query_terms)

                results.append(
                    {
                        "rank": rank,
                        "slug": slug,
                        "title": title,
                        "score": score,
                        "snippet": snippet,
                    }
                )

        return results

    def format_text(self, results: list[dict]) -> str:
        """Format results as human-readable text."""
        lines = []
        for r in results:
            line = f"{r['rank']}. {r['title']} ({r['slug']}) — score: {r['score']:.3f} — {r['snippet']}"
            lines.append(line)
        return "\n".join(lines)

    def format_json(self, results: list[dict]) -> str:
        """Format results as JSON."""
        output = []
        for r in results:
            output.append(
                {
                    "slug": r["slug"],
                    "title": r["title"],
                    "score": round(r["score"], 3),
                    "snippet": r["snippet"],
                }
            )
        return json.dumps(output, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Full-text search for wiki pages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("pages_dir", help="Directory containing .md wiki pages")
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "--top", type=int, default=10, help="Maximum results to show (default: 10)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    searcher = WikiSearcher(args.pages_dir)
    results = searcher.search(args.query, top=args.top)

    if args.json:
        print(searcher.format_json(results))
    else:
        output = searcher.format_text(results)
        if output:
            print(output)
        else:
            print("No results found.")


if __name__ == "__main__":
    main()
