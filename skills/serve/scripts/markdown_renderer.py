"""
Markdown renderer for wiki pages.

Converts wiki markdown to HTML with special transformations for the wiki web UI:
- Wiki links: [[slug]] → <a href="/wiki/slug">Slug Title</a>
- Section expand buttons: Injected after h2/h3 headings
- Table of contents: Generated from headings
- Source citations: (Source: path/to/file.md) → styled citation links
- Code blocks: Syntax highlighting support
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin


class WikiRenderer:
    """Renders wiki markdown to HTML with wiki-specific transformations."""

    def __init__(self):
        """Initialize the markdown renderer."""
        self.md = MarkdownIt("commonmark", {"breaks": True, "html": True})
        self.md.enable("table")
        self.md.use(front_matter_plugin)
        self.md.use(footnote_plugin)

    def render(
        self,
        content_md: str,
        slug: str | None = None,
        existing_slugs: set | None = None,
        page_resolver=None,
        wiki_dir: str | None = None,
    ) -> str:
        """
        Render markdown content to HTML with wiki transformations.

        Args:
            content_md: Raw markdown content
            slug: Page slug (for section expand buttons)
            existing_slugs: Set of valid wiki page slugs (for redlink detection)
            page_resolver: Callable(slug, section) -> str for transclusion
            wiki_dir: Path to .wiki directory (for dataview queries)

        Returns:
            HTML string
        """
        # Render base markdown
        html = self.md.render(content_md)

        # Transform wiki links (with transclusion support)
        html = self._transform_wiki_links(html, existing_slugs, page_resolver)

        # Inject expand buttons after h2/h3 headings
        if slug:
            html = self._inject_expand_buttons(html, slug)

        # Transform source citations
        html = self._transform_citations(html)

        # Transform dataview query blocks
        if wiki_dir:
            html = self._transform_dataview_blocks(html, wiki_dir)

        return html

    def render_page(
        self,
        page_dict: dict[str, Any],
        existing_slugs: set | None = None,
    ) -> dict[str, str]:
        """
        Render a complete wiki page with metadata.

        Args:
            page_dict: Page dictionary from WikiStore.get_page with keys:
                - slug: Page slug
                - title: Page title
                - content_md: Markdown content
                - type: Page type (e.g., 'concept', 'guide')
                - confidence: Confidence level (e.g., 'high', 'medium', 'low')
                - sources: List of source URLs or file paths
                - related: List of related page slugs
                - metadata: Additional metadata dict
            existing_slugs: Set of valid wiki page slugs

        Returns:
            Dictionary with keys:
                - html: Rendered page HTML
                - toc_html: Table of contents HTML
                - title: Page title
                - metadata: Rendered metadata HTML
        """
        slug = page_dict.get("slug", "")
        title = page_dict.get("title", "")
        content_md = page_dict.get("content_md", "")
        page_type = page_dict.get("type", "")
        confidence = page_dict.get("confidence", "")
        sources = page_dict.get("sources", [])
        related = page_dict.get("related", [])

        # Render main content
        html = self.render(content_md, slug=slug, existing_slugs=existing_slugs)

        # Generate table of contents
        toc_html = self._generate_toc(html)

        # Generate metadata section
        metadata_html = self._render_metadata(page_type, confidence, sources, related)

        return {
            "html": html,
            "toc_html": toc_html,
            "title": title,
            "metadata": metadata_html,
        }

    def _transform_wiki_links(
        self, html: str, existing_slugs: set | None = None,
        page_resolver=None,
    ) -> str:
        """
        Transform wiki link patterns to HTML links, with block references and transclusion.

        Supports:
        - [[slug]] — basic wiki link
        - [[slug|display text]] — custom display text
        - [[slug#heading]] — section link
        - [[slug#heading|display]] — section link with custom text
        - ![[slug#heading]] — transclusion (embed section content inline)
        """

        def replace_transclusion(match):
            """Handle ![[slug#section]] transclusion."""
            content = match.group(1)
            slug = content.split("#")[0].split("|")[0].strip()
            section = ""
            if "#" in content:
                section = content.split("#")[1].split("|")[0].strip()

            # Try to resolve the content
            if page_resolver and section:
                section_content = page_resolver(slug, section)
                if section_content:
                    section_html = self.md.render(section_content)
                    title = self._title_from_slug(slug)
                    return (
                        f'<div class="transclusion">'
                        f'<div class="transclusion-header">'
                        f'Transcluded from <a href="/wiki/{slug}#{slugify(section)}" class="wiki-link">{title} &rsaquo; {section}</a>'
                        f'</div>'
                        f'<div class="transclusion-content">{section_html}</div>'
                        f'</div>'
                    )

            # Fallback: render as a link
            display = self._title_from_slug(slug)
            if section:
                display += f" > {section}"
            return f'<a href="/wiki/{slug}#{slugify(section)}" class="wiki-link transclusion-link">📎 {display}</a>'

        def replace_wiki_link(match):
            full = match.group(0)
            content = match.group(1)

            # Parse slug, section, display text
            slug = content
            section = ""
            display_text = ""

            if "|" in content:
                slug_part, display_text = content.split("|", 1)
                slug_part = slug_part.strip()
                display_text = display_text.strip()
            else:
                slug_part = content.strip()

            if "#" in slug_part:
                slug, section = slug_part.split("#", 1)
                slug = slug.strip()
                section = section.strip()
            else:
                slug = slug_part.strip()

            if not display_text:
                display_text = self._title_from_slug(slug)
                if section:
                    display_text += f" > {section}"

            # Build href
            href = f"/wiki/{slug}"
            if section:
                href += f"#{slugify(section)}"

            # Determine if link is missing
            base_slug = slug
            is_missing = existing_slugs is not None and base_slug not in existing_slugs
            missing_class = " wiki-link-missing" if is_missing else ""

            return f'<a href="{href}" class="wiki-link{missing_class}">{display_text}</a>'

        # First pass: handle transclusions ![[...]]
        transclusion_pattern = r"!\[\[([^\]]+)\]\]"
        result = re.sub(transclusion_pattern, replace_transclusion, html)

        # Second pass: handle regular wiki links [[...]]
        pattern = r"\[\[([^\]]+)\]\]"
        result = re.sub(pattern, replace_wiki_link, result)

        return result

    def _inject_expand_buttons(self, html: str, slug: str) -> str:
        """
        Inject expand buttons after h2 and h3 headings.

        Args:
            html: HTML content
            slug: Page slug

        Returns:
            HTML with expand buttons injected
        """

        def inject_button(match):
            heading = match.group(0)
            heading_level = match.group(1)  # "h2" or "h3"
            heading_text = match.group(2)  # text content

            # Extract plain text from heading (remove any nested HTML)
            plain_text = re.sub(r"<[^>]+>", "", heading_text)

            button = f'<button class="expand-btn" data-slug="{slug}" data-section="{plain_text}">Expand</button>'
            return heading + button

        # Pattern: <h2>...</h2> or <h3>...</h3>
        pattern = r"(<(h[23])>.*?</\2>)"
        result = re.sub(pattern, inject_button, html, flags=re.DOTALL)

        return result

    def _generate_toc(self, html: str) -> str:
        """
        Generate a table of contents from h2 and h3 headings.

        Args:
            html: HTML content

        Returns:
            HTML table of contents
        """
        # Extract headings
        headings = []
        heading_pattern = r"<(h[23])>([^<]+)</\1>"
        for match in re.finditer(heading_pattern, html):
            level = int(match.group(1)[1])  # 2 or 3
            text = match.group(2)
            slug_id = slugify(text)
            headings.append({"level": level, "text": text, "id": slug_id})

        if not headings:
            return ""

        # Build nested list
        toc_html = '<div class="toc"><nav><ul>'
        current_level = 2

        for heading in headings:
            level = heading["level"]

            # Adjust nesting
            if level > current_level:
                for _ in range(level - current_level):
                    toc_html += "<ul>"
            elif level < current_level:
                for _ in range(current_level - level):
                    toc_html += "</ul>"

            current_level = level
            toc_html += f'<li><a href="#{heading["id"]}">{heading["text"]}</a></li>'

        # Close remaining lists
        for _ in range(current_level - 2):
            toc_html += "</ul>"

        toc_html += "</ul></nav></div>"

        return toc_html

    def _transform_dataview_blocks(self, html: str, wiki_dir: str | None = None) -> str:
        """
        Render ```dataview code blocks as live query results.

        Executes frontmatter queries and renders results as HTML tables inline.
        """
        import subprocess
        import sys

        def replace_dataview(match):
            query = match.group(1).strip()
            if not query or not wiki_dir:
                return f'<pre class="dataview-error">No wiki directory configured for dataview queries</pre>'

            try:
                bin_dir = Path(__file__).parent.parent.parent.parent / "bin"
                result = subprocess.run(
                    [sys.executable, str(bin_dir / "query.py"), "exec", str(Path(wiki_dir) / "pages"), query],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode != 0:
                    return f'<pre class="dataview-error">Query error: {result.stderr[:200]}</pre>'

                data = json.loads(result.stdout)
                if not data:
                    return '<div class="dataview-empty">No results</div>'

                # Render as HTML table
                keys = list(data[0].keys())
                rows_html = ""
                for row in data[:50]:  # Cap at 50 rows
                    cells = "".join(
                        f'<td>{self._format_cell(row.get(k, ""))}</td>' for k in keys
                    )
                    rows_html += f"<tr>{cells}</tr>"

                headers = "".join(f"<th>{k}</th>" for k in keys)
                return (
                    f'<div class="dataview-results">'
                    f'<table class="dataview-table"><thead><tr>{headers}</tr></thead>'
                    f'<tbody>{rows_html}</tbody></table>'
                    f'<div class="dataview-meta">{len(data)} results</div></div>'
                )
            except Exception as e:
                logger.error(f"Dataview query error: {e}", exc_info=True)
                return f'<pre class="dataview-error">Error: {str(e)[:200]}</pre>'

        import json
        pattern = r'<code class="language-dataview">(.*?)</code>'
        result = re.sub(pattern, replace_dataview, html, flags=re.DOTALL)

        # Also handle pre-wrapped version
        pattern2 = r'<pre><code class="language-dataview">(.*?)</code></pre>'
        result = re.sub(pattern2, replace_dataview, result, flags=re.DOTALL)

        return result

    def _format_cell(self, value) -> str:
        """Format a cell value for dataview table display."""
        if value is None:
            return ""
        s = str(value)
        # Convert wiki slugs to links
        if re.match(r'^[a-z0-9-]+$', s) and len(s) > 2:
            return f'<a href="/wiki/{s}" class="wiki-link">{self._title_from_slug(s)}</a>'
        return s

    def _transform_citations(self, html: str) -> str:
        """
        Transform (Source: path/to/file.md) patterns into styled citation links.

        Args:
            html: HTML content

        Returns:
            HTML with transformed citations
        """

        def replace_citation(match):
            path = match.group(1)
            # Create a styled citation
            return f'<span class="source-citation"><a href="/source/{path}">{path}</a></span>'

        # Pattern for (Source: ...)
        pattern = r"\(Source:\s*([^\)]+)\)"
        result = re.sub(pattern, replace_citation, html)

        return result

    def _render_metadata(
        self,
        page_type: str,
        confidence: str,
        sources: list[str],
        related: list[str],
    ) -> str:
        """
        Generate metadata section HTML.

        Args:
            page_type: Page type
            confidence: Confidence level
            sources: List of sources
            related: List of related page slugs

        Returns:
            HTML for metadata section
        """
        metadata_html = '<div class="page-metadata">'

        if page_type:
            metadata_html += f'<div class="metadata-item"><span class="label">Type:</span> <span class="value">{page_type}</span></div>'

        if confidence:
            metadata_html += f'<div class="metadata-item"><span class="label">Confidence:</span> <span class="value confidence-{confidence.lower()}">{confidence}</span></div>'

        if sources:
            metadata_html += '<div class="metadata-item"><span class="label">Sources:</span><ul class="sources-list">'
            for source in sources:
                # Check if it's a URL or file path
                if source.startswith("http://") or source.startswith("https://"):
                    metadata_html += (
                        f'<li><a href="{source}" target="_blank">{source}</a></li>'
                    )
                else:
                    metadata_html += f"<li><code>{source}</code></li>"
            metadata_html += "</ul></div>"

        if related:
            metadata_html += '<div class="metadata-item"><span class="label">Related:</span><ul class="related-list">'
            for slug in related:
                title = self._title_from_slug(slug)
                metadata_html += (
                    f'<li><a href="/wiki/{slug}" class="wiki-link">{title}</a></li>'
                )
            metadata_html += "</ul></div>"

        metadata_html += "</div>"

        return metadata_html

    @staticmethod
    def _title_from_slug(slug: str) -> str:
        """
        Convert a slug to a title (e.g., 'machine-learning' → 'Machine Learning').

        Args:
            slug: URL-safe slug

        Returns:
            Title-cased display text
        """
        return " ".join(word.capitalize() for word in slug.split("-"))


def slugify(text: str) -> str:
    """
    Convert text to a URL-safe slug.

    Args:
        text: Text to slugify

    Returns:
        URL-safe slug (lowercase, hyphens for spaces)
    """
    # Convert to lowercase
    text = text.lower()
    # Replace spaces and underscores with hyphens
    text = re.sub(r"[\s_]+", "-", text)
    # Remove non-alphanumeric characters except hyphens
    text = re.sub(r"[^a-z0-9-]", "", text)
    # Replace multiple consecutive hyphens with single hyphen
    text = re.sub(r"-+", "-", text)
    # Strip hyphens from start and end
    text = text.strip("-")
    return text


def extract_wiki_links(content_md: str) -> list[str]:
    """
    Extract all wiki link slugs from markdown content.

    Args:
        content_md: Raw markdown content

    Returns:
        List of slugs referenced in [[slug]] patterns
    """
    pattern = r"\[\[([^\]]+)\]\]"
    matches = re.findall(pattern, content_md)

    slugs = []
    for match in matches:
        # Handle [[slug|display text]]
        if "|" in match:
            slug = match.split("|", 1)[0].strip()
        else:
            slug = match.strip()
        slugs.append(slug)

    return slugs
