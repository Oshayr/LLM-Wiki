#!/usr/bin/env python3
"""rag.py — RAG pipeline for wiki Q&A with citations.

Usage:
    python3 rag.py query <pages_dir> "<question>" [--budget N] [--json]
    python3 rag.py context <pages_dir> "<question>" [--top N]

Retrieves relevant wiki chunks via TF-IDF full-text search, formats them as a
cited context block for LLM consumption. Citations use [[slug#section]] notation.
"""

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

from wiki_logging import get_logger

logger = get_logger(__name__)


def _chunk_page(slug: str, content: str) -> list[dict]:
    """Split a page into section chunks for RAG context."""
    chunks = []

    # Strip frontmatter
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            body = parts[2]

    lines = body.split("\n")
    current_section = "intro"
    current_lines = []

    for line in lines:
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            # Save previous chunk
            text = "\n".join(current_lines).strip()
            if text and len(text) > 20:
                chunks.append({
                    "slug": slug,
                    "section": current_section,
                    "text": text[:2000],
                })

            section_text = heading_match.group(2).strip()
            current_section = re.sub(r"[^a-z0-9]+", "-", section_text.lower()).strip("-")
            current_lines = [line]
        else:
            current_lines.append(line)

    # Save final chunk
    text = "\n".join(current_lines).strip()
    if text and len(text) > 20:
        chunks.append({
            "slug": slug,
            "section": current_section,
            "text": text[:2000],
        })

    return chunks


def build_rag_context(
    pages_dir: str, question: str, token_budget: int = 4000, top_k: int = 8
) -> dict:
    """Build RAG context from wiki for a question.

    Returns {context_chunks, formatted_prompt, total_tokens_est}.
    """
    pages_dir = Path(pages_dir)

    sys.path.insert(0, str(Path(__file__).parent))

    # Use TF-IDF full-text search
    spec = importlib.util.spec_from_file_location(
        "search_fulltext",
        str(Path(__file__).parent / "search-fulltext.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    searcher = mod.WikiSearcher(str(pages_dir))
    results = searcher.search(question, top=top_k * 2)

    # Build chunks from search results
    chunks = []
    total_chars = 0
    char_budget = token_budget * 4  # Rough chars-to-tokens

    seen = set()
    for r in results:
        slug = r["slug"]
        if slug in seen:
            continue
        seen.add(slug)

        # Read the page and chunk it
        page_path = pages_dir / f"{slug}.md"
        if not page_path.exists():
            continue

        content = page_path.read_text(encoding="utf-8")
        page_chunks = _chunk_page(slug, content)

        for chunk in page_chunks:
            text = chunk["text"]
            if total_chars + len(text) > char_budget:
                remaining = char_budget - total_chars
                if remaining > 100:
                    text = text[:remaining] + "..."
                    chunk["text"] = text
                else:
                    break

            chunk["score"] = r.get("score", 0)
            chunks.append(chunk)
            total_chars += len(text)

            if len(chunks) >= top_k:
                break

        if len(chunks) >= top_k:
            break

    # Format the prompt
    context_text = ""
    for i, chunk in enumerate(chunks, 1):
        ref = f"[[{chunk['slug']}#{chunk['section']}]]"
        context_text += f"\n--- Source {i}: {ref} ---\n"
        context_text += chunk["text"] + "\n"

    formatted_prompt = f"""You are a wiki Q&A assistant. Answer the question using ONLY the provided wiki context.
Cite your sources using [[page-slug#section]] notation after each claim.
If the context doesn't contain enough information, say so clearly.

## Wiki Context
{context_text}

## Question
{question}

## Instructions
- Answer concisely and accurately
- Cite every factual claim with [[page-slug#section]]
- If sources disagree, note the contradiction
- Do not make claims not supported by the context"""

    return {
        "context_chunks": chunks,
        "formatted_prompt": formatted_prompt,
        "total_tokens_est": len(formatted_prompt) // 4,
        "chunks_used": len(chunks),
    }


def verify_citations(response: str, valid_refs: set[str]) -> list[dict]:
    """Verify that citations in a response are grounded in the context."""
    citations = re.findall(r"\[\[([^\]]+)\]\]", response)
    issues = []

    for cite in citations:
        slug = cite.split("#")[0]
        if slug not in valid_refs and cite not in valid_refs:
            issues.append({
                "citation": cite,
                "issue": "ungrounded",
                "message": f"Citation [[{cite}]] not found in provided context",
            })

    return issues


def main():
    parser = argparse.ArgumentParser(
        description="RAG pipeline for wiki Q&A",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    query_p = subparsers.add_parser("query", help="Build RAG context for a question")
    query_p.add_argument("pages_dir")
    query_p.add_argument("question")
    query_p.add_argument("--budget", type=int, default=4000, help="Token budget for context")
    query_p.add_argument("--json", action="store_true")

    ctx_p = subparsers.add_parser("context", help="Get context chunks only")
    ctx_p.add_argument("pages_dir")
    ctx_p.add_argument("question")
    ctx_p.add_argument("--top", type=int, default=8)

    args = parser.parse_args()

    if args.command == "query":
        result = build_rag_context(args.pages_dir, args.question, token_budget=args.budget)
        logger.info("RAG context built", extra={"chunks": result["chunks_used"], "tokens_est": result["total_tokens_est"]})
        if hasattr(args, "json") and args.json:
            print(result["formatted_prompt"])
        else:
            print(json.dumps({
                "chunks_used": result["chunks_used"],
                "total_tokens_est": result["total_tokens_est"],
                "context_chunks": result["context_chunks"],
            }, indent=2))

    elif args.command == "context":
        result = build_rag_context(args.pages_dir, args.question, top_k=args.top)
        print(json.dumps(result["context_chunks"], indent=2))


if __name__ == "__main__":
    main()
