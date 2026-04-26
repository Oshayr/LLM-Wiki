# Wiki Integration Rules

> Behavioral reference for the `llm-wiki-github` plugin's agents and skills. The agent definitions cite this file to keep their system prompts focused.

Storage is the target repository's **GitHub Wiki** (`https://github.com/<owner>/<repo>/wiki`). The plugin maintains a local git clone of `<owner>/<repo>.wiki.git` under `${CLAUDE_PLUGIN_DATA}/wiki-cache/` as a read/write buffer. These rules apply to every conversation where this plugin is active.

## WRITE to the wiki when:

- You research any topic — save findings as a wiki page
- You generate an analysis, comparison, or summary worth keeping
- You solve a non-trivial problem — save the solution pattern
- The user shares ideas, plans, decisions, or requirements
- You discover facts, relationships, or patterns during work
- The user says "save this", "remember this", "note this", or similar
- Any tool or feature produces structured knowledge
- You create documentation, guides, or reference material

## READ from the wiki when:

- The user asks about a topic — check the wiki FIRST before web search
- You need context about the project, its decisions, or history
- You're about to research something — check if the wiki already covers it
- The user references a concept that might have a wiki page
- You need to ground your answer in existing knowledge

## HOW to write:

- Use `/wiki-write` or the `wiki-writer` agent. All writes go through `bin/wiki_repo.py`.
- Auto-clones the target's GitHub Wiki on first use. If the wiki has never been initialized on GitHub, the tool exits with code 10 and asks the user to create the first page in the browser.
- Every page carries an HTML-comment metadata block (see `bin/frontmatter_fmt.py`) with: `title`, `slug`, `type`, `confidence`, `created`, `updated`, plus optional `sources`, `related`, `tags`, `freshness_tier`, `has_contradictions`, `stale`.
- Use `[[wiki-links]]` (GitHub-Wiki-native) to connect related concepts. `[[Title|slug]]` when the display text differs from the slug.
- Choose the right page type: concept, idea, status, rules, config, skill, brainstorming, memory, reference (or a custom template under `${CLAUDE_PLUGIN_ROOT}/templates/`).
- Include inline web links `[text](url)` to sources.

## HOW to read:

- Use `/wiki-read` or the `wiki-reader` agent. Reads flow through `bin/wiki_repo.py` (pulls before reading if the cache is stale).
- Use `bin/search-fulltext.py` for ranked results.
- Three depths: quick (sidebar scan only), standard (articles + auto-research if missing), deep (broader multi-source research).

## Sharing

Every page is a real GitHub Wiki page, browsable at `https://github.com/<owner>/<repo>/wiki/<Title-Case-Slug>`. Call `wiki_repo.page_url(slug)` (or the `wiki_url` MCP tool) to get the canonical URL to share. Whether it is publicly accessible depends on the underlying repository's visibility — the plugin does not assume either way.

## Page types and when to use them:

| Type | When to use |
|------|-------------|
| concept | Standard knowledge article — facts, explanations, details |
| idea | Single idea with problem/solution/pros/cons evaluation |
| brainstorming | Freeform ideas list with themes and priority voting |
| status | Current state dashboard — metrics, action items, blockers |
| rules | Numbered rules/policies with exceptions and examples |
| config | Key-value settings with defaults and descriptions |
| skill | Command/tool documentation with usage examples |
| memory | Persistent facts, relationships, key information |
| reference | Links and pointers to external resources |
| source | Source-summary page with URL, extracted key takeaways |
| log | Append-only record (e.g. `activity-log`) |
| custom | User-defined template in `${CLAUDE_PLUGIN_ROOT}/templates/<type>.md` |
