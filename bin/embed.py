#!/usr/bin/env python3
"""embed.py — Vector embedding index for wiki semantic search.

Usage:
    python3 embed.py build <pages_dir>                     — Full rebuild of embedding index
    python3 embed.py update <pages_dir> <slug>             — Update embeddings for one page
    python3 embed.py search <pages_dir> <query> [--top N]  — Semantic search
    python3 embed.py hybrid <pages_dir> <query> [--top N]  — Hybrid BM25 + semantic (RRF)
    python3 embed.py status <pages_dir>                    — Index status and stats

Chunks pages by markdown headings. Each section becomes a chunk with heading
hierarchy as metadata. Embeddings stored in SQLite via sqlite-vec extension.
Falls back to numpy cosine similarity if sqlite-vec is unavailable.

Model: all-MiniLM-L6-v2 (384 dimensions) via ONNX Runtime — no PyTorch needed.
"""

import argparse
import hashlib
import json
import re
import sqlite3
import struct
import sys
from datetime import UTC, datetime
from pathlib import Path

# Lazy imports for heavy deps
_model = None
_tokenizer = None
_HAS_SQLITE_VEC = None


def _check_sqlite_vec():
    """Check if sqlite-vec extension is available."""
    global _HAS_SQLITE_VEC
    if _HAS_SQLITE_VEC is not None:
        return _HAS_SQLITE_VEC
    try:
        import sqlite_vec

        _HAS_SQLITE_VEC = True
    except ImportError:
        _HAS_SQLITE_VEC = False
    return _HAS_SQLITE_VEC


def _get_model():
    """Lazy-load the ONNX embedding model."""
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        # Download model if needed
        model_dir = Path.home() / ".cache" / "llm-wiki" / "models"
        model_dir.mkdir(parents=True, exist_ok=True)

        model_path = model_dir / "all-MiniLM-L6-v2.onnx"
        tokenizer_path = model_dir / "tokenizer.json"

        if not model_path.exists() or not tokenizer_path.exists():
            print("Downloading all-MiniLM-L6-v2 model (~23MB)...", file=sys.stderr)
            _download_model(model_dir)

        _tokenizer = Tokenizer.from_file(str(tokenizer_path))
        _tokenizer.enable_truncation(max_length=512)
        _tokenizer.enable_padding(length=512)

        _model = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        return _model, _tokenizer
    except ImportError as e:
        print(
            f"Error: Missing dependency — {e}\n"
            "Install with: pip install onnxruntime tokenizers",
            file=sys.stderr,
        )
        sys.exit(1)


def _download_model(model_dir: Path):
    """Download model files from Hugging Face."""
    import urllib.request

    base_url = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main"

    files = {
        "model.onnx": "onnx/model.onnx",
        "tokenizer.json": "tokenizer.json",
    }

    for local_name, remote_path in files.items():
        url = f"{base_url}/{remote_path}"
        dest = model_dir / local_name.replace("model.onnx", "all-MiniLM-L6-v2.onnx")
        if local_name == "tokenizer.json":
            dest = model_dir / "tokenizer.json"

        if dest.exists():
            continue

        print(f"  Downloading {local_name}...", file=sys.stderr)
        try:
            urllib.request.urlretrieve(url, str(dest))
        except Exception as e:
            print(f"  Failed to download {url}: {e}", file=sys.stderr)
            raise


def embed_text(text: str) -> list[float]:
    """Generate embedding for a text string. Returns 384-dim float list."""
    import numpy as np

    model, tokenizer = _get_model()

    encoded = tokenizer.encode(text)
    input_ids = np.array([encoded.ids], dtype=np.int64)
    attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
    token_type_ids = np.zeros_like(input_ids, dtype=np.int64)

    outputs = model.run(
        None,
        {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": token_type_ids,
        },
    )

    # Mean pooling over token embeddings
    token_embeddings = outputs[0]  # (1, seq_len, 384)
    mask_expanded = attention_mask[:, :, np.newaxis].astype(np.float32)
    summed = np.sum(token_embeddings * mask_expanded, axis=1)
    count = np.sum(mask_expanded, axis=1)
    mean_pooled = summed / np.maximum(count, 1e-9)

    # L2 normalize
    norm = np.linalg.norm(mean_pooled, axis=1, keepdims=True)
    normalized = mean_pooled / np.maximum(norm, 1e-9)

    return normalized[0].tolist()


def embed_to_bytes(embedding: list[float]) -> bytes:
    """Convert float list to bytes for SQLite storage."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def bytes_to_embed(data: bytes) -> list[float]:
    """Convert bytes back to float list."""
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


def chunk_markdown(content: str, slug: str) -> list[dict]:
    """Split markdown into chunks by headings.

    Returns list of {chunk_id, slug, section, text, heading_hierarchy}.
    """
    chunks = []
    lines = content.split("\n")

    # Strip frontmatter
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                lines = lines[i + 1 :]
                break

    current_section = "intro"
    current_hierarchy = []
    current_lines = []

    for line in lines:
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            # Save previous chunk
            text = "\n".join(current_lines).strip()
            if text and len(text) > 20:
                chunk_id = f"{slug}#{current_section}"
                chunks.append(
                    {
                        "chunk_id": chunk_id,
                        "slug": slug,
                        "section": current_section,
                        "text": text[:2000],  # Cap at ~500 tokens
                        "heading_hierarchy": " > ".join(current_hierarchy)
                        if current_hierarchy
                        else "",
                    }
                )

            # Start new section
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            section_slug = re.sub(r"[^a-z0-9]+", "-", heading_text.lower()).strip("-")
            current_section = section_slug

            # Update hierarchy
            current_hierarchy = current_hierarchy[: level - 1]
            while len(current_hierarchy) < level - 1:
                current_hierarchy.append("")
            current_hierarchy.append(heading_text)

            current_lines = [line]
        else:
            current_lines.append(line)

    # Save final chunk
    text = "\n".join(current_lines).strip()
    if text and len(text) > 20:
        chunk_id = f"{slug}#{current_section}"
        chunks.append(
            {
                "chunk_id": chunk_id,
                "slug": slug,
                "section": current_section,
                "text": text[:2000],
                "heading_hierarchy": " > ".join(current_hierarchy)
                if current_hierarchy
                else "",
            }
        )

    # If no chunks from headings, treat whole page as one chunk
    if not chunks:
        full_text = "\n".join(lines).strip()
        if full_text:
            chunks.append(
                {
                    "chunk_id": f"{slug}#full",
                    "slug": slug,
                    "section": "full",
                    "text": full_text[:2000],
                    "heading_hierarchy": "",
                }
            )

    return chunks


class EmbeddingIndex:
    """Manages vector embeddings in SQLite."""

    DIMS = 384  # all-MiniLM-L6-v2

    def __init__(self, pages_dir: Path):
        self.pages_dir = Path(pages_dir)
        self.cache_dir = self.pages_dir.parent / "cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.db_path = self.cache_dir / "vectors.db"
        self.use_vec = _check_sqlite_vec()
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)

        if self.use_vec:
            import sqlite_vec

            conn.enable_load_extension(True)
            sqlite_vec.load(conn)

        # Chunks table stores text and metadata
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                slug TEXT NOT NULL,
                section TEXT NOT NULL,
                text TEXT NOT NULL,
                heading_hierarchy TEXT DEFAULT '',
                content_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_slug ON chunks(slug)")

        # Embeddings table stores raw vectors
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                chunk_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
            )
        """)

        # Page-level embeddings (mean of chunk embeddings)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_embeddings (
                slug TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                chunk_count INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        """)

        conn.commit()
        conn.close()

    def _content_hash(self, text: str) -> str:
        """SHA256 hash of text content (first 16 chars)."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def build(self) -> dict:
        """Full rebuild of embedding index."""
        md_files = sorted(self.pages_dir.glob("*.md"))
        stats = {"pages": 0, "chunks": 0, "skipped": 0}

        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM embeddings")
        conn.execute("DELETE FROM chunks")
        conn.execute("DELETE FROM page_embeddings")
        conn.commit()

        for md_file in md_files:
            slug = md_file.stem
            try:
                content = md_file.read_text(encoding="utf-8")
                chunks = chunk_markdown(content, slug)

                if not chunks:
                    stats["skipped"] += 1
                    continue

                now = datetime.now(UTC).isoformat()
                page_embeddings = []
                full_content_hash = self._content_hash(content)

                for chunk in chunks:
                    text_for_embed = chunk["text"]
                    if chunk["heading_hierarchy"]:
                        text_for_embed = (
                            chunk["heading_hierarchy"] + "\n" + text_for_embed
                        )

                    embedding = embed_text(text_for_embed)
                    emb_bytes = embed_to_bytes(embedding)
                    content_hash = full_content_hash

                    conn.execute(
                        """INSERT OR REPLACE INTO chunks
                           (chunk_id, slug, section, text, heading_hierarchy, content_hash, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            chunk["chunk_id"],
                            slug,
                            chunk["section"],
                            chunk["text"],
                            chunk["heading_hierarchy"],
                            content_hash,
                            now,
                        ),
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO embeddings (chunk_id, embedding) VALUES (?, ?)",
                        (chunk["chunk_id"], emb_bytes),
                    )

                    page_embeddings.append(embedding)
                    stats["chunks"] += 1

                # Compute page-level embedding (mean of chunks)
                if page_embeddings:
                    import numpy as np

                    mean_emb = np.mean(page_embeddings, axis=0).tolist()
                    conn.execute(
                        """INSERT OR REPLACE INTO page_embeddings
                           (slug, embedding, chunk_count, updated_at)
                           VALUES (?, ?, ?, ?)""",
                        (slug, embed_to_bytes(mean_emb), len(page_embeddings), now),
                    )

                stats["pages"] += 1
                if stats["pages"] % 10 == 0:
                    conn.commit()
                    print(
                        f"  Indexed {stats['pages']} pages, {stats['chunks']} chunks...",
                        file=sys.stderr,
                    )

            except Exception as e:
                print(f"Error indexing {slug}: {e}", file=sys.stderr)
                stats["skipped"] += 1

        conn.commit()
        conn.close()
        return stats

    def update(self, slug: str) -> dict:
        """Update embeddings for a single page."""
        md_file = self.pages_dir / f"{slug}.md"
        if not md_file.exists():
            return {"error": f"Page '{slug}' not found"}

        content = md_file.read_text(encoding="utf-8")
        chunks = chunk_markdown(content, slug)

        conn = sqlite3.connect(self.db_path)
        now = datetime.now(UTC).isoformat()

        # Check if content changed
        cursor = conn.cursor()
        cursor.execute(
            "SELECT content_hash FROM chunks WHERE slug = ? LIMIT 1", (slug,)
        )
        existing = cursor.fetchone()
        new_hash = self._content_hash(content)
        if existing and existing[0] == new_hash:
            conn.close()
            return {"status": "unchanged", "slug": slug}

        # Remove old chunks for this page
        conn.execute("DELETE FROM embeddings WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE slug = ?)", (slug,))
        conn.execute("DELETE FROM chunks WHERE slug = ?", (slug,))

        page_embeddings = []
        for chunk in chunks:
            text_for_embed = chunk["text"]
            if chunk["heading_hierarchy"]:
                text_for_embed = chunk["heading_hierarchy"] + "\n" + text_for_embed

            embedding = embed_text(text_for_embed)
            emb_bytes = embed_to_bytes(embedding)
            content_hash = self._content_hash(chunk["text"])

            conn.execute(
                """INSERT OR REPLACE INTO chunks
                   (chunk_id, slug, section, text, heading_hierarchy, content_hash, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk["chunk_id"],
                    slug,
                    chunk["section"],
                    chunk["text"],
                    chunk["heading_hierarchy"],
                    content_hash,
                    now,
                ),
            )
            conn.execute(
                "INSERT OR REPLACE INTO embeddings (chunk_id, embedding) VALUES (?, ?)",
                (chunk["chunk_id"], emb_bytes),
            )
            page_embeddings.append(embedding)

        # Update page-level embedding
        if page_embeddings:
            import numpy as np

            mean_emb = np.mean(page_embeddings, axis=0).tolist()
            conn.execute(
                """INSERT OR REPLACE INTO page_embeddings
                   (slug, embedding, chunk_count, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (slug, embed_to_bytes(mean_emb), len(page_embeddings), now),
            )

        conn.commit()
        conn.close()
        return {"status": "updated", "slug": slug, "chunks": len(chunks)}

    def search(self, query: str, top: int = 10) -> list[dict]:
        """Semantic search using cosine similarity."""
        import numpy as np

        query_embedding = embed_text(query)
        query_vec = np.array(query_embedding, dtype=np.float32)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT chunk_id, embedding FROM embeddings"
        )

        results = []
        for chunk_id, emb_bytes in cursor.fetchall():
            emb = np.array(bytes_to_embed(emb_bytes), dtype=np.float32)
            # Cosine similarity (vectors are L2-normalized)
            similarity = float(np.dot(query_vec, emb))
            results.append((chunk_id, similarity))

        results.sort(key=lambda x: x[1], reverse=True)
        results = results[:top]

        # Fetch chunk details
        output = []
        for chunk_id, score in results:
            cursor.execute(
                "SELECT slug, section, text, heading_hierarchy FROM chunks WHERE chunk_id = ?",
                (chunk_id,),
            )
            row = cursor.fetchone()
            if row:
                output.append(
                    {
                        "chunk_id": chunk_id,
                        "slug": row[0],
                        "section": row[1],
                        "text": row[2][:300],
                        "heading_hierarchy": row[3],
                        "score": round(score, 4),
                    }
                )

        conn.close()
        return output

    def hybrid_search(self, query: str, pages_dir: Path = None, top: int = 10) -> list[dict]:
        """Hybrid search combining BM25 keyword + semantic vector via RRF."""
        # Get semantic results
        semantic_results = self.search(query, top=top * 2)

        # Get keyword results via TF-IDF
        from pathlib import Path as P

        search_dir = pages_dir or self.pages_dir
        try:
            # Import sibling module
            sys.path.insert(0, str(Path(__file__).parent))
            from importlib import import_module

            # Use search-fulltext module
            spec = __import__("importlib").util.spec_from_file_location(
                "search_fulltext",
                str(Path(__file__).parent / "search-fulltext.py"),
            )
            mod = __import__("importlib").util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            searcher = mod.WikiSearcher(str(search_dir))
            keyword_results = searcher.search(query, top=top * 2)
        except Exception:
            keyword_results = []

        # Reciprocal Rank Fusion
        k = 60  # RRF constant
        scores = {}  # slug -> rrf_score

        for rank, res in enumerate(semantic_results):
            slug = res["slug"]
            rrf = 1.0 / (k + rank + 1)
            scores[slug] = scores.get(slug, 0) + rrf

        for rank, res in enumerate(keyword_results):
            slug = res["slug"]
            rrf = 1.0 / (k + rank + 1)
            scores[slug] = scores.get(slug, 0) + rrf

        # Merge results, keeping best details from each source
        details = {}
        for res in semantic_results:
            slug = res["slug"]
            if slug not in details:
                details[slug] = {
                    "slug": slug,
                    "section": res.get("section", ""),
                    "text": res.get("text", ""),
                    "semantic_score": res.get("score", 0),
                }

        for res in keyword_results:
            slug = res["slug"]
            if slug not in details:
                details[slug] = {
                    "slug": slug,
                    "title": res.get("title", ""),
                    "text": res.get("snippet", ""),
                    "keyword_score": res.get("score", 0),
                }
            else:
                details[slug]["title"] = res.get("title", details[slug].get("title", ""))
                details[slug]["keyword_score"] = res.get("score", 0)

        # Sort by RRF score
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top]

        output = []
        for slug, rrf_score in ranked:
            info = details.get(slug, {"slug": slug})
            info["rrf_score"] = round(rrf_score, 6)
            output.append(info)

        return output

    def get_page_embedding(self, slug: str) -> list[float] | None:
        """Get the page-level embedding for a slug."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT embedding FROM page_embeddings WHERE slug = ?", (slug,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return bytes_to_embed(row[0])
        return None

    def find_similar_pages(
        self, slug: str, top: int = 10, exclude_linked: set | None = None
    ) -> list[dict]:
        """Find pages similar to a given page by cosine similarity."""
        import numpy as np

        target_emb = self.get_page_embedding(slug)
        if target_emb is None:
            return []

        target_vec = np.array(target_emb, dtype=np.float32)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT slug, embedding FROM page_embeddings WHERE slug != ?", (slug,))

        results = []
        for page_slug, emb_bytes in cursor.fetchall():
            if exclude_linked and page_slug in exclude_linked:
                continue
            emb = np.array(bytes_to_embed(emb_bytes), dtype=np.float32)
            similarity = float(np.dot(target_vec, emb))
            results.append({"slug": page_slug, "similarity": round(similarity, 4)})

        conn.close()
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top]

    def cluster_pages(self, n_clusters: int = 10) -> list[dict]:
        """Cluster pages by embedding similarity using k-means."""
        import numpy as np

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT slug, embedding FROM page_embeddings")
        rows = cursor.fetchall()
        conn.close()

        if len(rows) < n_clusters:
            n_clusters = max(2, len(rows) // 2)

        slugs = [r[0] for r in rows]
        embeddings = np.array(
            [bytes_to_embed(r[1]) for r in rows], dtype=np.float32
        )

        # Simple k-means
        n_clusters = min(n_clusters, len(slugs))
        rng = np.random.default_rng(42)
        centers = embeddings[rng.choice(len(embeddings), n_clusters, replace=False)]

        for _ in range(20):  # Max iterations
            # Assign
            dists = np.dot(embeddings, centers.T)
            labels = np.argmax(dists, axis=1)

            # Update centers
            new_centers = np.zeros_like(centers)
            for i in range(n_clusters):
                mask = labels == i
                if mask.any():
                    new_centers[i] = embeddings[mask].mean(axis=0)
                    new_centers[i] /= max(np.linalg.norm(new_centers[i]), 1e-9)
                else:
                    new_centers[i] = centers[i]

            if np.allclose(centers, new_centers, atol=1e-6):
                break
            centers = new_centers

        # Build cluster output
        clusters = {}
        for slug, label in zip(slugs, labels):
            label = int(label)
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(slug)

        return [
            {"cluster_id": cid, "pages": pages, "size": len(pages)}
            for cid, pages in sorted(clusters.items())
        ]

    def status(self) -> dict:
        """Get index status."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM chunks")
        chunk_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT slug) FROM chunks")
        page_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM page_embeddings")
        page_emb_count = cursor.fetchone()[0]

        # DB file size
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        conn.close()
        return {
            "chunks": chunk_count,
            "pages_indexed": page_count,
            "page_embeddings": page_emb_count,
            "db_size_mb": round(db_size / 1024 / 1024, 2),
            "db_path": str(self.db_path),
            "sqlite_vec": self.use_vec,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Vector embedding index for wiki semantic search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    build_p = subparsers.add_parser("build", help="Full rebuild of embedding index")
    build_p.add_argument("pages_dir")

    update_p = subparsers.add_parser("update", help="Update embeddings for one page")
    update_p.add_argument("pages_dir")
    update_p.add_argument("slug")

    search_p = subparsers.add_parser("search", help="Semantic search")
    search_p.add_argument("pages_dir")
    search_p.add_argument("query")
    search_p.add_argument("--top", type=int, default=10)
    search_p.add_argument("--json", action="store_true")

    hybrid_p = subparsers.add_parser("hybrid", help="Hybrid BM25 + semantic search")
    hybrid_p.add_argument("pages_dir")
    hybrid_p.add_argument("query")
    hybrid_p.add_argument("--top", type=int, default=10)
    hybrid_p.add_argument("--json", action="store_true")

    status_p = subparsers.add_parser("status", help="Index status")
    status_p.add_argument("pages_dir")

    args = parser.parse_args()
    idx = EmbeddingIndex(args.pages_dir)

    if args.command == "build":
        stats = idx.build()
        print(
            f"Built embedding index: {stats['pages']} pages, {stats['chunks']} chunks"
            + (f" ({stats['skipped']} skipped)" if stats["skipped"] else "")
        )

    elif args.command == "update":
        result = idx.update(args.slug)
        print(json.dumps(result, indent=2))

    elif args.command == "search":
        results = idx.search(args.query, top=args.top)
        if hasattr(args, "json") and args.json:
            print(json.dumps(results, indent=2))
        else:
            for i, r in enumerate(results, 1):
                print(
                    f"{i}. [{r['score']:.3f}] {r['slug']}#{r['section']} — {r['text'][:100]}"
                )

    elif args.command == "hybrid":
        results = idx.hybrid_search(args.query, top=args.top)
        if hasattr(args, "json") and args.json:
            print(json.dumps(results, indent=2))
        else:
            for i, r in enumerate(results, 1):
                print(
                    f"{i}. [RRF:{r['rrf_score']:.4f}] {r['slug']} — {r.get('text', '')[:100]}"
                )

    elif args.command == "status":
        status = idx.status()
        print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
