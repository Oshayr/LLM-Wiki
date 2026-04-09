#!/usr/bin/env python3
"""
Wiki export tool for CScratch plugin.

Exports entire wiki to single-file formats: markdown, HTML, JSON knowledge graph, or statistics.

Usage:
    export.py <wiki_dir> --md      Export as markdown with TOC
    export.py <wiki_dir> --html    Export as self-contained HTML
    export.py <wiki_dir> --json    Export as JSON knowledge graph
    export.py <wiki_dir> --stats   Print wiki statistics
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from wiki_logging import get_logger

logger = get_logger(__name__)

# Type definitions
WikiNode = dict
WikiEdge = dict
PageMetadata = dict


class WikiParser:
    """Parses wiki files and extracts links."""

    # Pattern for [[slug]] or [[slug|type]] links
    LINK_PATTERN = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")

    # Pattern for frontmatter
    FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

    def __init__(self, wiki_dir: Path):
        self.wiki_dir = Path(wiki_dir)
        self.pages: dict[str, str] = {}
        self.metadata: dict[str, PageMetadata] = {}
        self.links: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def load_wiki(self) -> bool:
        """Load all markdown files from wiki directory."""
        if not self.wiki_dir.exists():
            logger.error("Wiki directory not found", extra={"path": str(self.wiki_dir)})
            return False

        md_files = list(self.wiki_dir.glob("**/*.md"))
        if not md_files:
            logger.warning("No markdown files found", extra={"path": str(self.wiki_dir)})
            return True

        for md_file in md_files:
            slug = md_file.stem
            try:
                content = md_file.read_text(encoding="utf-8")
                self.pages[slug] = content
                self._extract_metadata(slug, content)
                self._extract_links(slug, content)
            except Exception as e:
                logger.warning("Failed to load file", extra={"file": str(md_file), "error": str(e)}, exc_info=True)

        return True

    def _extract_metadata(self, slug: str, content: str) -> None:
        """Extract frontmatter metadata."""
        match = self.FRONTMATTER_PATTERN.search(content)
        metadata = {"slug": slug, "type": "note", "confidence": "medium"}

        if match:
            fm_text = match.group(1)
            for line in fm_text.split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    metadata[key.strip()] = val.strip()

        # Extract title from first H1 if present
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if title_match and "title" not in metadata:
            metadata["title"] = title_match.group(1).strip()
        else:
            metadata["title"] = metadata.get("title", slug)

        # Extract tags
        tags = []
        if "tags" in metadata:
            tags = [t.strip() for t in metadata["tags"].split(",")]
        metadata["tags"] = tags

        self.metadata[slug] = metadata

    def _extract_links(self, slug: str, content: str) -> None:
        """Extract all [[slug]] and [[slug|type]] links."""
        for match in self.LINK_PATTERN.finditer(content):
            target_slug = match.group(1).strip()
            link_type = match.group(2).strip() if match.group(2) else "reference"
            self.links[slug].append((target_slug, link_type))

    def get_page_content(self, slug: str) -> str:
        """Get page content without frontmatter."""
        content = self.pages.get(slug, "")
        return self.FRONTMATTER_PATTERN.sub("", content).strip()

    def resolve_index(self) -> list[str]:
        """Get page order from index.md if it exists."""
        index_file = self.wiki_dir / "index.md"
        if not index_file.exists():
            return sorted(self.pages.keys())

        try:
            content = index_file.read_text(encoding="utf-8")
            slugs = []
            for match in self.LINK_PATTERN.finditer(content):
                slug = match.group(1).strip()
                if slug in self.pages:
                    slugs.append(slug)
            return slugs if slugs else sorted(self.pages.keys())
        except Exception:
            return sorted(self.pages.keys())


class MarkdownExporter:
    """Exports wiki as markdown with TOC."""

    def __init__(self, parser: WikiParser):
        self.parser = parser

    def export(self) -> str:
        """Generate markdown export."""
        output = []

        # Generate TOC
        output.append("# Wiki Export\n")
        output.append(f"*Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
        output.append("## Table of Contents\n")

        page_order = self.parser.resolve_index()
        for slug in page_order:
            title = self.parser.metadata.get(slug, {}).get("title", slug)
            output.append(f"- [{title}](#{slug})\n")

        output.append("\n---\n\n")

        # Export pages
        for slug in page_order:
            metadata = self.parser.metadata.get(slug, {})
            title = metadata.get("title", slug)

            output.append(f"## {title}\n\n")

            # Metadata block
            if (
                metadata.get("type")
                or metadata.get("tags")
                or metadata.get("confidence")
            ):
                output.append("**Metadata:**\n")
                if metadata.get("type"):
                    output.append(f"- Type: {metadata['type']}\n")
                if metadata.get("confidence"):
                    output.append(f"- Confidence: {metadata['confidence']}\n")
                if metadata.get("tags"):
                    output.append(f"- Tags: {', '.join(metadata['tags'])}\n")
                output.append("\n")

            # Page content with converted links
            content = self.parser.get_page_content(slug)
            content = self._convert_links(content)
            output.append(content)
            output.append("\n\n---\n\n")

        return "".join(output)

    def _convert_links(self, content: str) -> str:
        """Convert [[slug]] links to [slug](#slug) anchor links."""

        def replace_link(match):
            slug = match.group(1).strip()
            label = slug.replace("-", " ").title()
            return f"[{label}](#{slug})"

        return self.parser.LINK_PATTERN.sub(replace_link, content)


class HTMLExporter:
    """Exports wiki as self-contained HTML."""

    CSS = """
    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }

    body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        color: #333;
        background: #f5f5f5;
        line-height: 1.6;
    }

    .container {
        display: flex;
        max-width: 1400px;
        margin: 0 auto;
        background: white;
        box-shadow: 0 0 20px rgba(0,0,0,0.1);
    }

    .sidebar {
        width: 280px;
        background: #f9f9f9;
        border-right: 1px solid #e0e0e0;
        padding: 20px;
        overflow-y: auto;
        max-height: 100vh;
        position: sticky;
        top: 0;
    }

    .sidebar h2 {
        font-size: 14px;
        font-weight: 700;
        text-transform: uppercase;
        color: #666;
        margin-top: 20px;
        margin-bottom: 10px;
        letter-spacing: 0.5px;
    }

    .sidebar h2:first-child {
        margin-top: 0;
    }

    .sidebar ul {
        list-style: none;
    }

    .sidebar li {
        margin: 5px 0;
    }

    .sidebar a {
        color: #0066cc;
        text-decoration: none;
        font-size: 13px;
    }

    .sidebar a:hover {
        text-decoration: underline;
    }

    .sidebar a.active {
        color: #004499;
        font-weight: 600;
    }

    .search-box {
        margin-bottom: 20px;
        padding: 10px;
        border: 1px solid #ddd;
        border-radius: 4px;
        font-size: 13px;
        width: 100%;
    }

    .main {
        flex: 1;
        padding: 40px;
        overflow-y: auto;
        max-height: 100vh;
    }

    .page {
        display: none;
    }

    .page.active {
        display: block;
    }

    h1 {
        font-size: 32px;
        margin-bottom: 20px;
        color: #222;
    }

    h2 {
        font-size: 24px;
        margin-top: 30px;
        margin-bottom: 15px;
        color: #333;
        border-bottom: 2px solid #e0e0e0;
        padding-bottom: 10px;
    }

    h3 {
        font-size: 18px;
        margin-top: 20px;
        margin-bottom: 10px;
        color: #444;
    }

    h4, h5, h6 {
        margin-top: 15px;
        margin-bottom: 8px;
    }

    p {
        margin-bottom: 15px;
    }

    a {
        color: #0066cc;
        text-decoration: none;
    }

    a:hover {
        text-decoration: underline;
    }

    code {
        background: #f4f4f4;
        padding: 2px 6px;
        border-radius: 3px;
        font-family: 'Monaco', 'Menlo', monospace;
        font-size: 13px;
    }

    pre {
        background: #f4f4f4;
        padding: 15px;
        border-radius: 4px;
        overflow-x: auto;
        margin-bottom: 15px;
    }

    pre code {
        background: none;
        padding: 0;
    }

    blockquote {
        border-left: 4px solid #0066cc;
        padding-left: 15px;
        margin-left: 0;
        margin-bottom: 15px;
        color: #666;
    }

    ul, ol {
        margin-left: 20px;
        margin-bottom: 15px;
    }

    li {
        margin-bottom: 5px;
    }

    .metadata {
        background: #f9f9f9;
        padding: 12px;
        border-left: 3px solid #0066cc;
        margin-bottom: 20px;
        font-size: 13px;
    }

    .metadata-item {
        margin: 5px 0;
    }

    .tag {
        display: inline-block;
        background: #e3f2fd;
        color: #1976d2;
        padding: 3px 8px;
        border-radius: 3px;
        font-size: 12px;
        margin-right: 5px;
    }

    .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 30px;
        padding-bottom: 20px;
        border-bottom: 2px solid #e0e0e0;
    }

    .header h1 {
        margin: 0;
    }

    .export-info {
        font-size: 12px;
        color: #999;
    }

    table {
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 15px;
    }

    th, td {
        padding: 10px;
        text-align: left;
        border-bottom: 1px solid #ddd;
    }

    th {
        background: #f9f9f9;
        font-weight: 600;
    }

    @media print {
        .sidebar { display: none; }
        .container { display: block; }
        .main { padding: 0; max-height: none; }
        .page { display: block !important; page-break-after: always; }
    }

    @media (max-width: 800px) {
        .container { flex-direction: column; }
        .sidebar { width: 100%; max-height: none; border-right: none; border-bottom: 1px solid #e0e0e0; }
        .main { padding: 20px; }
    }
    """

    def __init__(self, parser: WikiParser):
        self.parser = parser

    def export(self) -> str:
        """Generate HTML export."""
        page_order = self.parser.resolve_index()

        # Group pages by type
        pages_by_type = defaultdict(list)
        for slug in page_order:
            page_type = self.parser.metadata.get(slug, {}).get("type", "note")
            pages_by_type[page_type].append(slug)

        # Build sidebar
        sidebar_html = '<input type="text" class="search-box" id="search" placeholder="Search pages...">'
        for page_type in sorted(pages_by_type.keys()):
            sidebar_html += f"<h2>{self._escape_html(page_type.title())}</h2>\n<ul>\n"
            for slug in pages_by_type[page_type]:
                title = self.parser.metadata.get(slug, {}).get("title", slug)
                safe_slug = self._escape_html(slug).replace("'", "\\'")
                sidebar_html += f'<li><a href="#{self._escape_html(slug)}" onclick="showPage(\'{safe_slug}\')">{self._escape_html(title)}</a></li>\n'
            sidebar_html += "</ul>\n"

        # Build main content
        main_html = '<div class="header">'
        main_html += f'<h1>Wiki Export</h1><div class="export-info">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>'
        main_html += "</div>\n"

        for slug in page_order:
            metadata = self.parser.metadata.get(slug, {})
            title = metadata.get("title", slug)
            content = self.parser.get_page_content(slug)
            content = self._convert_links(content)

            # Build metadata block
            meta_block = ""
            if (
                metadata.get("type")
                or metadata.get("tags")
                or metadata.get("confidence")
            ):
                meta_block = '<div class="metadata">'
                if metadata.get("type"):
                    meta_block += f'<div class="metadata-item"><strong>Type:</strong> {metadata["type"]}</div>'
                if metadata.get("confidence"):
                    meta_block += f'<div class="metadata-item"><strong>Confidence:</strong> {metadata["confidence"]}</div>'
                if metadata.get("tags"):
                    tags_html = " ".join(
                        f'<span class="tag">{tag}</span>' for tag in metadata["tags"]
                    )
                    meta_block += f'<div class="metadata-item"><strong>Tags:</strong> {tags_html}</div>'
                meta_block += "</div>"

            main_html += f'<div class="page" id="page-{slug}">\n'
            main_html += f"<h1>{self._escape_html(title)}</h1>\n"
            main_html += meta_block
            main_html += f"{self._markdown_to_html(content)}\n"
            main_html += "</div>\n"

        # JavaScript for interactivity
        js = (
            """
        function showPage(slug) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById('page-' + slug).classList.add('active');
            window.location.hash = slug;
        }

        document.getElementById('search').addEventListener('keyup', function(e) {
            const query = e.target.value.toLowerCase();
            document.querySelectorAll('.sidebar a').forEach(link => {
                const text = link.textContent.toLowerCase();
                link.closest('li').style.display = text.includes(query) ? '' : 'none';
            });
        });

        window.addEventListener('hashchange', function() {
            const slug = window.location.hash.slice(1);
            if (slug) showPage(slug);
        });

        window.addEventListener('load', function() {
            const slug = window.location.hash.slice(1);
            if (slug) showPage(slug);
            else showPage('"""
            + (page_order[0] if page_order else "")
            + """');
        });
        """
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Wiki Export</title>
    <style>{self.CSS}</style>
</head>
<body>
    <div class="container">
        <div class="sidebar">{sidebar_html}</div>
        <div class="main">{main_html}</div>
    </div>
    <script>{js}</script>
</body>
</html>
"""
        return html

    def _convert_links(self, content: str) -> str:
        """Convert [[slug]] links to clickable anchors."""

        def replace_link(match):
            slug = match.group(1).strip()
            label = slug.replace("-", " ").title()
            safe_slug = self._escape_html(slug).replace("'", "\\'")
            return f'<a href="#{self._escape_html(slug)}" onclick="showPage(\'{safe_slug}\')">{self._escape_html(label)}</a>'

        return self.parser.LINK_PATTERN.sub(replace_link, content)

    def _markdown_to_html(self, content: str) -> str:
        """Basic markdown to HTML conversion."""
        lines = content.split("\n")
        html = []
        in_code = False
        in_list = False

        for line in lines:
            if line.startswith("```"):
                if in_code:
                    html.append("</code></pre>")
                    in_code = False
                else:
                    lang = line[3:].strip()
                    html.append(f'<pre><code class="language-{lang}">')
                    in_code = True
                continue

            if in_code:
                html.append(self._escape_html(line) + "\n")
                continue

            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                title = line.lstrip("#").strip()
                html.append(f"<h{level}>{self._escape_html(title)}</h{level}>")
                continue

            if line.startswith("- ") or line.startswith("* "):
                if not in_list:
                    html.append("<ul>")
                    in_list = True
                item = line.lstrip("- *").strip()
                html.append(f"<li>{self._escape_html(item)}</li>")
                continue

            if in_list and line.strip() == "":
                html.append("</ul>")
                in_list = False
                continue

            if line.startswith("> "):
                quote = line[2:].strip()
                html.append(f"<blockquote>{self._escape_html(quote)}</blockquote>")
                continue

            if line.strip():
                html.append(f"<p>{self._escape_html(line)}</p>")

        if in_list:
            html.append("</ul>")
        if in_code:
            html.append("</code></pre>")

        return "\n".join(html)

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )


class JSONExporter:
    """Exports wiki as JSON knowledge graph."""

    def __init__(self, parser: WikiParser):
        self.parser = parser

    def export(self) -> str:
        """Generate JSON knowledge graph."""
        nodes = []
        edges = []

        for slug, metadata in self.parser.metadata.items():
            node = {
                "id": slug,
                "title": metadata.get("title", slug),
                "type": metadata.get("type", "note"),
                "confidence": metadata.get("confidence", "medium"),
                "tags": metadata.get("tags", []),
            }
            nodes.append(node)

        # Build edges from links
        seen_edges = set()
        for from_slug, links in self.parser.links.items():
            for to_slug, link_type in links:
                edge_key = (from_slug, to_slug, link_type)
                if edge_key not in seen_edges:
                    edges.append({"from": from_slug, "to": to_slug, "type": link_type})
                    seen_edges.add(edge_key)

        result = {
            "nodes": nodes,
            "edges": edges,
            "meta": {
                "exported": datetime.now().isoformat(),
                "page_count": len(nodes),
                "edge_count": len(edges),
            },
        }

        return json.dumps(result, indent=2)


class StatsExporter:
    """Exports wiki statistics."""

    def __init__(self, parser: WikiParser):
        self.parser = parser

    def export(self) -> str:
        """Generate statistics output."""
        output = []
        output.append("=== Wiki Statistics ===\n")
        output.append(f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        # Page count by type
        pages_by_type = defaultdict(int)
        for metadata in self.parser.metadata.values():
            page_type = metadata.get("type", "note")
            pages_by_type[page_type] += 1

        output.append("Pages by Type:\n")
        for page_type in sorted(pages_by_type.keys()):
            output.append(f"  {page_type}: {pages_by_type[page_type]}\n")
        output.append(f"  TOTAL: {len(self.parser.pages)}\n\n")

        # Link statistics
        total_links = sum(len(links) for links in self.parser.links.values())
        avg_links = total_links / len(self.parser.pages) if self.parser.pages else 0

        output.append("Link Statistics:\n")
        output.append(f"  Total links: {total_links}\n")
        output.append(f"  Average links per page: {avg_links:.1f}\n")

        # Orphan count (pages with no incoming or outgoing links)
        inbound = defaultdict(int)
        for links in self.parser.links.values():
            for to_slug, _ in links:
                inbound[to_slug] += 1

        orphans = 0
        for slug in self.parser.pages.keys():
            if slug not in self.parser.links and slug not in inbound:
                orphans += 1

        output.append(f"  Orphaned pages: {orphans}\n\n")

        # Most-connected pages
        link_counts = defaultdict(int)
        for links in self.parser.links.values():
            for to_slug, _ in links:
                link_counts[to_slug] += 1

        for outgoing_slug, outgoing_links in self.parser.links.items():
            link_counts[outgoing_slug] += len(outgoing_links)

        # Recalculate: incoming + outgoing
        connectivity = defaultdict(int)
        for slug in self.parser.pages.keys():
            connectivity[slug] = len(self.parser.links.get(slug, [])) + inbound.get(
                slug, 0
            )

        output.append("Top 10 Most Connected Pages:\n")
        for slug, count in sorted(connectivity.items(), key=lambda x: -x[1])[:10]:
            title = self.parser.metadata.get(slug, {}).get("title", slug)
            output.append(f"  {title}: {count} links\n")
        output.append("\n")

        # Confidence distribution
        confidence_dist = defaultdict(int)
        for metadata in self.parser.metadata.values():
            conf = metadata.get("confidence", "unknown")
            confidence_dist[conf] += 1

        output.append("Confidence Distribution:\n")
        for conf in ["high", "medium", "low", "unknown"]:
            count = confidence_dist.get(conf, 0)
            if count > 0:
                output.append(f"  {conf}: {count}\n")

        return "".join(output)


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    wiki_dir = sys.argv[1]
    export_format = sys.argv[2]

    # Parse wiki
    parser = WikiParser(wiki_dir)
    if not parser.load_wiki():
        logger.error("Failed to load wiki")
        sys.exit(1)

    if not parser.pages:
        logger.error("No pages found to export")
        sys.exit(1)

    # Export
    if export_format == "--md":
        exporter = MarkdownExporter(parser)
        output = exporter.export()
        print(output)

    elif export_format == "--html":
        exporter = HTMLExporter(parser)
        output = exporter.export()
        print(output)

    elif export_format == "--json":
        exporter = JSONExporter(parser)
        output = exporter.export()
        print(output)

    elif export_format == "--stats":
        exporter = StatsExporter(parser)
        output = exporter.export()
        print(output)

    else:
        logger.error("Unknown export format", extra={"format": export_format})
        print(f"Error: Unknown format '{export_format}'")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
