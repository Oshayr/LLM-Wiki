# LLM Wiki — Integration Rules

The wiki at `.wiki/` is your persistent knowledge store. These rules apply to EVERY conversation where this plugin is active.

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

- The user asks about a topic — check wiki FIRST before web search
- You need context about the project, its decisions, or history
- You're about to research something — check if the wiki already covers it
- The user references a concept that might have a wiki page
- You need to ground your answer in existing knowledge

## HOW to write:

- Use `/wiki-write` or the `wiki-writer` agent to create or update pages
- Auto-creates `.wiki/` if it doesn't exist yet
- Every page needs YAML frontmatter: title, type, confidence, created, updated
- Include `[[wiki-links]]` to connect related concepts
- Choose the right page type: concept, idea, status, rules, config, skill, brainstorming, memory, reference
- Include inline web links `[text](url)` to sources

## HOW to read:

- Use `/wiki-read` or the `wiki-reader` agent to search and retrieve pages
- Check `.wiki/index.md` for page listings
- Use full-text search for specific queries
- Three depths: quick (index only), standard (articles + auto-research if missing), deep (everything + raw + research)

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
| custom | User-defined type — structure defined in `.wiki/templates/<type-name>.md` |
