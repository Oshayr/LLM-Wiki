# llm-wiki-github

A Claude Code plugin that uses a project's **GitHub Wiki** as a persistent, git-backed knowledge base. Every page is a real wiki page on github.com, browsable by you and your team.

```
your repo on GitHub              the plugin                  Claude inside Claude Code
──────────────────              ─────────────                ─────────────────────────
<owner>/<repo>.wiki.git  <────  bin/wiki_repo.py  <────  wiki-writer / wiki-reader / wiki-auditor
   (git-backed storage)         (clone, pull, push)       (skills: /wiki-write, /wiki-read, /wiki-maintain)
```

## Why this plugin

- **Storage you already have.** A GitHub Wiki is a git repo (`<owner>/<repo>.wiki.git`) — version-controlled, browsable in any browser, shareable with collaborators, ready for backup and export.
- **No separate UI to maintain.** The GitHub Wiki itself is the browse surface. No local web server, no embedded DB.
- **Claude does the writing.** `/wiki-write` compiles pages from URLs, files, or pasted text and pushes them. `/wiki-read` answers cited questions, and if the wiki doesn't know something it researches inline and ingests the findings.
- **Autonomous by default.** Ingest and update run end-to-end without pausing for confirmation.

## How it works

1. You tell the plugin which GitHub repo's wiki to use (env var, config file, or autodetect from the current git checkout).
2. On first use it clones `<owner>/<repo>.wiki.git` into `${CLAUDE_PLUGIN_DATA}/wiki-cache/`.
3. Every read does a pull-if-stale (5 min TTL). Every write does a pull, writes the file, rebuilds `_Sidebar.md`, commits with `Wiki-Agent:` / `Wiki-Page:` trailers, and pushes with rebase-on-conflict retry.
4. Page metadata is stored as an HTML-comment JSON block at the foot of each page — invisible on the rendered wiki, one-line diffs on edit.

## First-time setup

1. **Install the plugin** via the Claude Code marketplace or by cloning this repo into your plugins directory.
2. **Ensure git can push to the target repo.** If you have `gh auth login`, git's credential helper picks it up; otherwise configure an HTTPS token or SSH key for `github.com` as normal. No `GITHUB_TOKEN` env var needed.
3. **Create the first page on the GitHub Wiki in the browser.** GitHub requires this one-time bootstrap before `git clone <owner>/<repo>.wiki.git` will work. Go to `https://github.com/<owner>/<repo>/wiki`, click "Create the first page", save anything (a stub `# Home` is fine).
4. **Point the plugin at your repo.** Any one of:
   - Run `/wiki-write` from a clone of the repo — autodetect from `git remote get-url origin`.
   - `export LLM_WIKI_TARGET=<owner>/<repo>` in your shell.
   - Copy `config/default.yaml` to `${CLAUDE_PLUGIN_DATA}/config.yaml` and set `owner:` / `repo:`.
5. **Try it.** `/wiki-write "note: Claude Code is an interactive agent..."` — check `https://github.com/<owner>/<repo>/wiki/Claude-Code` in a minute.

## Commands

| Command | What it does |
|---|---|
| `/wiki-write <url\|file\|text>` | Ingest and push a new page (or several). |
| `/wiki-write --update <slug>` | Refresh an existing page from new source material. |
| `/wiki-write --refresh-stale` | Find pages past their freshness-tier TTL and update them. |
| `/wiki-read <question>` | Cited answer from the wiki; research + ingest on miss. |
| `/wiki-read quick <q>` | Sidebar scan only, fastest. |
| `/wiki-read deep <q>` | Broader multi-source research. |
| `/wiki-maintain` | Lint, flag duplicates, upgrade confidence, rebuild `_Sidebar.md`. |

Under the hood these are served by three sub-agents — `wiki-writer`, `wiki-reader`, `wiki-auditor` — all of which route file I/O through `bin/wiki_repo.py`.

## Configuration

Target resolution priority (first match wins):

1. `LLM_WIKI_TARGET=<owner>/<repo>` env var.
2. `${CLAUDE_PLUGIN_DATA}/config.yaml` with `owner:` and `repo:`.
3. Autodetected from the CWD's `git remote get-url origin`.

See `config/default.yaml` for the full set of knobs (cache dir, pull TTL).

## Authentication

The plugin shells out to `git` — it does not implement its own GitHub auth. That means:

- Whatever credential works for `git push git@github.com:<owner>/<repo>.git` (or the HTTPS equivalent) also works here.
- `gh auth login` is the simplest path on a laptop.
- For CI, use a PAT in `~/.git-credentials` or a deploy key.
- The plugin never reads your token — it's never in env vars or config.

## Troubleshooting

| Exit code | Meaning | Fix |
|---|---|---|
| 10 | Wiki not initialized on GitHub | Create the first page in the browser at `https://github.com/<owner>/<repo>/wiki`. |
| 11 | Network failure cloning/pushing | Retry; check GitHub status. |
| 12 | No target repo configured | Set `LLM_WIKI_TARGET`, populate `config.yaml`, or run from a clone of the target repo. |
| 13 | Auth rejected | Re-check `git push <repo>.wiki.git`; refresh `gh auth login`. |

## Development layout

```
llm-wiki-github/
  .claude-plugin/{plugin.json, marketplace.json}
  agents/           wiki-writer.md  wiki-reader.md  wiki-auditor.md
  bin/              wiki_repo.py  frontmatter_fmt.py  slug_title.py
                    tools.py  search-fulltext.py  diff.py
                    fetch.py  wiki_logging.py  exceptions.py
  config/default.yaml
  mcp_server/wiki-mcp-server.py
  rules/{wiki-integration.md, workflow.md}
  skills/{write,read,maintain}/SKILL.md
  templates/example-meeting-notes.md
  CONTRIBUTING.md  LICENSE  README.md  requirements.txt
```

Critical-path modules:
- `bin/wiki_repo.py` — the only place that ever touches git. Target resolution, clone, pull-if-stale, write+push, sidebar rebuild, attribution trailers.
- `bin/frontmatter_fmt.py` — the HTML-comment JSON metadata contract.
- `bin/slug_title.py` — deterministic slug ↔ Title-Case-Filename conversion.

## License

MIT — see `LICENSE`.
