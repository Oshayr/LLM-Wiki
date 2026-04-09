---
name: view
description: "Wiki dashboard — browse pages, view stats, knowledge graph, export. Use on: 'wiki dashboard', 'wiki stats', 'show wiki', 'wiki pages', 'list wiki', 'wiki graph', 'export wiki', 'wiki overview'."
---

# View

Dashboard, graph visualization, stats, and export for the wiki.

Find `.wiki/` by walking up from working directory. If not found, say "No wiki found."

## Arguments

- **`/view`** — dashboard summary (page count, recent activity, top topics)
- **`/view pages`** — list all pages grouped by type
- **`/view stats`** — detailed statistics (page count, links, confidence distribution, stale %)
- **`/view graph`** — knowledge graph visualization (Mermaid diagram)
- **`/view graph <slug>`** — graph centered on a specific page (2-hop neighborhood)
- **`/view export html`** — export entire wiki as single HTML file
- **`/view export md`** — export as single markdown bundle
- **`/view export json`** — export as JSON knowledge graph (nodes + edges)
- **`/view artifacts <type>`** — generate study guide, timeline, glossary, or comparison table

## Dashboard

Read `.wiki/index.md`, `.wiki/log.md`, `.wiki/overview.md`:
- Page count and breakdown by type
- Last 5 activity log entries
- Current open questions from overview.md
- Confidence distribution (high/medium/low)

## Graph

Read all pages, extract `[[wiki-links]]` and `related:` fields:
- Generate Mermaid flowchart showing page connections
- Color by type (concept=blue, entity=green, source=gray, idea=yellow)
- Highlight orphans (no incoming links) in red
- For `--slug`: show only 2-hop neighborhood of that page

## Export

- **HTML**: Render all pages through markdown → styled single HTML document
- **Markdown**: Concatenate all pages with `---` separators
- **JSON**: `{"nodes": [...], "edges": [...]}` knowledge graph format

## Artifacts

Generate derivative documents from wiki content:
- **`/view artifacts study-guide <topic>`** — structured study guide from topic cluster
- **`/view artifacts timeline <topic>`** — chronological timeline of events/developments
- **`/view artifacts glossary`** — terms and definitions from all pages
- **`/view artifacts compare <slug1> <slug2>`** — side-by-side comparison table
