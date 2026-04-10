#!/usr/bin/env python3
"""
Structured diff tool for wiki page updates.
Understands wiki page format (frontmatter + sections).
"""

import json
import sys
from pathlib import Path
from typing import Any

from wiki_logging import get_logger

logger = get_logger(__name__)


def parse_wiki_page(content: str) -> tuple[dict[str, str], dict[str, str]]:
    """
    Parse a wiki page into frontmatter dict and sections dict.

    Returns:
        (frontmatter_dict, sections_dict)
    """
    lines = content.split("\n")
    frontmatter = {}
    sections = {}

    # Parse frontmatter (between --- markers)
    if lines and lines[0].strip() == "---":
        end_idx = 1
        while end_idx < len(lines) and lines[end_idx].strip() != "---":
            line = lines[end_idx].strip()
            if ":" in line:
                key, value = line.split(":", 1)
                frontmatter[key.strip()] = value.strip()
            end_idx += 1

        # Parse body sections
        if end_idx < len(lines):
            body_lines = lines[end_idx + 1 :]
            current_section = None
            current_content = []

            for line in body_lines:
                if line.startswith("## "):
                    # Save previous section
                    if current_section is not None:
                        sections[current_section] = "\n".join(current_content).strip()
                    # Start new section
                    current_section = line[3:].strip()
                    current_content = []
                else:
                    if current_section is not None:
                        current_content.append(line)

            # Save last section
            if current_section is not None:
                sections[current_section] = "\n".join(current_content).strip()
    else:
        # No frontmatter, treat entire content as one section
        body_lines = lines
        current_section = None
        current_content = []

        for line in body_lines:
            if line.startswith("## "):
                if current_section is not None:
                    sections[current_section] = "\n".join(current_content).strip()
                current_section = line[3:].strip()
                current_content = []
            else:
                if current_section is not None:
                    current_content.append(line)
                else:
                    current_content.append(line)

        if current_section is not None:
            sections[current_section] = "\n".join(current_content).strip()
        elif current_content:
            sections["_content"] = "\n".join(current_content).strip()

    return frontmatter, sections


def extract_links(text: str) -> set:
    """Extract [[slug]] style wiki links from text."""
    links = set()
    words = text.split()
    for word in words:
        if word.startswith("[[") and word.endswith("]]"):
            slug = word[2:-2].strip()
            if slug:
                links.add(slug)
    return links


def get_slug_from_frontmatter(frontmatter: dict[str, str]) -> str:
    """Extract slug from frontmatter, defaulting to file slug if not present."""
    return frontmatter.get("slug", "unknown")


def count_line_changes(old_text: str, new_text: str) -> tuple[int, int]:
    """Count added and removed lines."""
    old_lines = set(old_text.split("\n")) if old_text else set()
    new_lines = set(new_text.split("\n")) if new_text else set()

    added = len(new_lines - old_lines)
    removed = len(old_lines - new_lines)

    return added, removed


def compare_wikis(old_content: str, new_content: str) -> dict[str, Any]:
    """
    Compare two wiki page versions and return structured diff.

    Returns:
        dict with frontmatter_changes, section_changes, links_added, links_removed, summary
    """
    old_fm, old_sections = parse_wiki_page(old_content)
    new_fm, new_sections = parse_wiki_page(new_content)

    # Compare frontmatter
    frontmatter_changes = []
    all_fm_keys = set(old_fm.keys()) | set(new_fm.keys())

    for key in sorted(all_fm_keys):
        old_val = old_fm.get(key, "")
        new_val = new_fm.get(key, "")

        if old_val == new_val:
            if old_val:
                frontmatter_changes.append(
                    {"field": key, "type": "unchanged", "value": old_val}
                )
        elif not old_val:
            frontmatter_changes.append({"field": key, "type": "added", "new": new_val})
        elif not new_val:
            frontmatter_changes.append(
                {"field": key, "type": "removed", "old": old_val}
            )
        else:
            # Determine if it's an "upgrade" or "modified"
            change_type = "modified"
            if key == "confidence":
                confidence_order = {"low": 1, "medium": 2, "high": 3}
                old_rank = confidence_order.get(old_val.lower(), 0)
                new_rank = confidence_order.get(new_val.lower(), 0)
                if new_rank > old_rank:
                    change_type = "upgraded"
                elif new_rank < old_rank:
                    change_type = "downgraded"

            frontmatter_changes.append(
                {"field": key, "type": change_type, "old": old_val, "new": new_val}
            )

    # Compare sections
    section_changes = []
    all_sections = set(old_sections.keys()) | set(new_sections.keys())

    for section in sorted(all_sections):
        old_text = old_sections.get(section, "")
        new_text = new_sections.get(section, "")

        if old_text == new_text:
            if old_text:
                section_changes.append({"section": section, "type": "unchanged"})
        elif not old_text:
            added, _ = count_line_changes("", new_text)
            section_changes.append(
                {"section": section, "type": "added", "lines_added": added}
            )
        elif not new_text:
            _, removed = count_line_changes(old_text, "")
            section_changes.append(
                {"section": section, "type": "removed", "lines_removed": removed}
            )
        else:
            added, removed = count_line_changes(old_text, new_text)
            section_changes.append(
                {
                    "section": section,
                    "type": "modified",
                    "lines_added": added,
                    "lines_removed": removed,
                }
            )

    # Extract and compare links
    old_links = set()
    new_links = set()

    for text in old_sections.values():
        old_links.update(extract_links(text))
    for text in new_sections.values():
        new_links.update(extract_links(text))

    links_added = sorted(new_links - old_links)
    links_removed = sorted(old_links - new_links)

    # Generate summary
    summary_parts = []

    # Count significant changes
    fm_changes = [c for c in frontmatter_changes if c["type"] != "unchanged"]
    if fm_changes:
        summary_parts.append(f"{len(fm_changes)} frontmatter change(s)")

    section_mods = [c for c in section_changes if c["type"] == "modified"]
    if section_mods:
        total_added = sum(c.get("lines_added", 0) for c in section_mods)
        total_removed = sum(c.get("lines_removed", 0) for c in section_mods)
        if total_added or total_removed:
            summary_parts.append(
                f"{total_added} lines added, {total_removed} lines removed"
            )

    section_adds = [c for c in section_changes if c["type"] == "added"]
    if section_adds:
        summary_parts.append(f"{len(section_adds)} new section(s)")

    section_rems = [c for c in section_changes if c["type"] == "removed"]
    if section_rems:
        summary_parts.append(f"{len(section_rems)} section(s) removed")

    if links_added:
        summary_parts.append(f"{len(links_added)} new link(s)")
    if links_removed:
        summary_parts.append(f"{len(links_removed)} link(s) removed")

    summary = ", ".join(summary_parts) if summary_parts else "No changes"

    return {
        "slug": get_slug_from_frontmatter(new_fm or old_fm),
        "frontmatter_changes": frontmatter_changes,
        "section_changes": section_changes,
        "links_added": links_added,
        "links_removed": links_removed,
        "summary": summary,
    }


def format_markdown_table(diff: dict[str, Any]) -> str:
    """Format diff as a markdown table."""
    lines = [
        f"## Wiki Page Diff: {diff['slug']}\n",
        "| Section | Change | Details |",
        "|---------|--------|---------|",
    ]

    # Frontmatter changes
    for change in diff["frontmatter_changes"]:
        section = f"Frontmatter: {change['field']}"
        change_type = change["type"]

        if change_type == "unchanged":
            details = f'"{change.get("value", "")}"'
        elif change_type == "added":
            details = f'+{change["new"]}'
        elif change_type == "removed":
            details = f'-{change["old"]}'
        elif change_type in ("modified", "upgraded", "downgraded"):
            details = f'{change["old"]} -> {change["new"]}'
        else:
            details = ""

        lines.append(f"| {section} | {change_type} | {details} |")

    # Section changes
    for change in diff["section_changes"]:
        section = change["section"]
        change_type = change["type"]

        if change_type == "unchanged":
            details = "(no changes)"
        elif change_type == "added":
            details = f"+{change.get('lines_added', 0)} lines"
        elif change_type == "removed":
            details = f"-{change.get('lines_removed', 0)} lines"
        elif change_type == "modified":
            added = change.get("lines_added", 0)
            removed = change.get("lines_removed", 0)
            details = f"+{added} -{removed} lines"
        else:
            details = ""

        lines.append(f"| {section} | {change_type} | {details} |")

    # Links
    if diff["links_added"] or diff["links_removed"]:
        if diff["links_added"]:
            details = "+" + ", +".join(diff["links_added"])
            lines.append(f"| Backlinks | added | {details} |")
        if diff["links_removed"]:
            details = "-" + ", -".join(diff["links_removed"])
            lines.append(f"| Backlinks | removed | {details} |")

    return "\n".join(lines)


def format_html_diff(diff: dict[str, Any]) -> str:
    """Format diff as a side-by-side HTML view with semantic annotations."""
    import html as html_mod

    parts = [
        '<div class="semantic-diff">',
        f'<h2>Diff: {html_mod.escape(diff["slug"])}</h2>',
        f'<div class="diff-summary">{html_mod.escape(diff["summary"])}</div>',
    ]

    # Frontmatter changes
    fm_changes = [c for c in diff["frontmatter_changes"] if c["type"] != "unchanged"]
    if fm_changes:
        parts.append('<h3>Frontmatter Changes</h3>')
        parts.append('<table class="diff-table"><thead><tr><th>Field</th><th>Change</th><th>Old</th><th>New</th></tr></thead><tbody>')
        for c in fm_changes:
            cls = {"added": "diff-add", "removed": "diff-del", "modified": "diff-mod", "upgraded": "diff-add", "downgraded": "diff-del"}.get(c["type"], "")
            old_val = html_mod.escape(str(c.get("old", "")))
            new_val = html_mod.escape(str(c.get("new", "")))
            parts.append(f'<tr class="{cls}"><td>{html_mod.escape(c["field"])}</td><td>{c["type"]}</td><td>{old_val}</td><td>{new_val}</td></tr>')
        parts.append('</tbody></table>')

    # Section changes
    section_mods = [c for c in diff["section_changes"] if c["type"] != "unchanged"]
    if section_mods:
        parts.append('<h3>Section Changes</h3>')
        for c in section_mods:
            cls = {"added": "diff-add", "removed": "diff-del", "modified": "diff-mod"}.get(c["type"], "")
            label = c["type"].upper()
            detail = ""
            if c["type"] == "added":
                detail = f'+{c.get("lines_added", 0)} lines'
            elif c["type"] == "removed":
                detail = f'-{c.get("lines_removed", 0)} lines'
            elif c["type"] == "modified":
                detail = f'+{c.get("lines_added", 0)} -{c.get("lines_removed", 0)} lines'
            parts.append(f'<div class="diff-section {cls}"><span class="diff-label">{label}</span> <strong>{html_mod.escape(c["section"])}</strong> <span class="diff-detail">{detail}</span></div>')

    # Link changes
    if diff["links_added"] or diff["links_removed"]:
        parts.append('<h3>Link Changes</h3>')
        for link in diff["links_added"]:
            parts.append(f'<div class="diff-add">+ [[{html_mod.escape(link)}]]</div>')
        for link in diff["links_removed"]:
            parts.append(f'<div class="diff-del">- [[{html_mod.escape(link)}]]</div>')

    parts.append('</div>')
    parts.append("""<style>
.semantic-diff { font-family: var(--wiki-font-ui, sans-serif); }
.diff-summary { color: var(--wiki-text-light, #666); margin-bottom: 16px; }
.diff-table { width: 100%; border-collapse: collapse; margin: 8px 0; }
.diff-table th, .diff-table td { padding: 6px 10px; border: 1px solid var(--wiki-border-light, #eee); text-align: left; font-size: 0.9em; }
.diff-add { background: #d4edda; color: #155724; padding: 4px 8px; margin: 2px 0; border-radius: 3px; }
.diff-del { background: #f8d7da; color: #721c24; padding: 4px 8px; margin: 2px 0; border-radius: 3px; }
.diff-mod { background: #fff3cd; color: #856404; padding: 4px 8px; margin: 2px 0; border-radius: 3px; }
.diff-section { padding: 6px 10px; margin: 4px 0; border-radius: 4px; }
.diff-label { font-size: 0.75em; font-weight: bold; text-transform: uppercase; }
.diff-detail { font-size: 0.85em; color: var(--wiki-text-light, #666); }
</style>""")
    return "\n".join(parts)


def main():
    """CLI entry point."""
    if len(sys.argv) < 3:
        print("Usage: diff.py [--json|--summary|--html] <old_file> <new_file>")
        sys.exit(1)

    # Parse arguments
    output_format = "markdown"
    old_file = None
    new_file = None

    args = sys.argv[1:]

    if args[0] == "--json":
        output_format = "json"
        old_file = args[1] if len(args) > 1 else None
        new_file = args[2] if len(args) > 2 else None
    elif args[0] == "--summary":
        output_format = "summary"
        old_file = args[1] if len(args) > 1 else None
        new_file = args[2] if len(args) > 2 else None
    elif args[0] == "--html":
        output_format = "html"
        old_file = args[1] if len(args) > 1 else None
        new_file = args[2] if len(args) > 2 else None
    else:
        old_file = args[0]
        new_file = args[1] if len(args) > 1 else None

    # Validate files
    if not old_file or not new_file:
        logger.error("Missing required file arguments")
        print("Error: both old_file and new_file are required")
        sys.exit(1)

    old_path = Path(old_file)
    new_path = Path(new_file)

    if not old_path.exists():
        logger.error("File does not exist", extra={"path": old_file})
        print(f"Error: {old_file} does not exist")
        sys.exit(1)

    if not new_path.exists():
        logger.error("File does not exist", extra={"path": new_file})
        print(f"Error: {new_file} does not exist")
        sys.exit(1)

    # Read files
    try:
        old_content = old_path.read_text()
        new_content = new_path.read_text()
    except Exception as e:
        logger.error("Error reading files", extra={"error": str(e)}, exc_info=True)
        print(f"Error reading files: {e}")
        sys.exit(1)

    # Generate diff
    diff = compare_wikis(old_content, new_content)

    # Output
    if output_format == "json":
        print(json.dumps(diff, indent=2))
    elif output_format == "summary":
        print(diff["summary"])
    elif output_format == "html":
        print(format_html_diff(diff))
    else:  # markdown
        print(format_markdown_table(diff))


if __name__ == "__main__":
    main()
