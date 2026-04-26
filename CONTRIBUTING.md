# Contributing to llm-wiki-github

## Ways to contribute

- **Bug reports** — open an issue with steps to reproduce
- **Feature requests** — open an issue describing the use case
- **Pull requests** — bug fixes, better conflict recovery, richer page templates, new agent behaviors

## Development setup

```bash
git clone https://github.com/Oshayr/llm-wiki-github
cd llm-wiki-github

pip install -r requirements.txt      # just `mcp`
```

Test the plugin locally by installing it into a Claude Code project:

```bash
claude plugin install ./
```

End-to-end test against a real GitHub Wiki:

```bash
# bash / zsh
export WIKI_GITHUB_TARGET=<your-user>/<scratch-repo>

# PowerShell
# $env:WIKI_GITHUB_TARGET = "<your-user>/<scratch-repo>"

python bin/wiki_repo.py resolve   # verify target resolution
python bin/wiki_repo.py ensure    # clone the wiki
python bin/wiki_repo.py sync      # pull + print HEAD
```

## Project structure

| Path | Purpose |
|------|---------|
| `agents/` | Sub-agent specs: `wiki-writer`, `wiki-reader`, `wiki-auditor`. |
| `bin/wiki_repo.py` | Single chokepoint for git-wiki I/O. Never bypass it. |
| `bin/frontmatter_fmt.py` | HTML-comment JSON metadata format. |
| `bin/slug_title.py` | Slug ↔ Title-Case-Filename conversion. |
| `bin/` (rest) | `tools.py`, `search-fulltext.py`, `diff.py`, `fetch.py`, plus `wiki_logging.py` and `exceptions.py`. |
| `mcp_server/` | FastMCP server wrapping `wiki_repo`. |
| `rules/` | Always-on behavioral rules. |
| `skills/` | Slash-command skill definitions. |
| `templates/` | Page skeletons for custom types. |

## Code style

- Python 3.11+ syntax (`X | Y` unions, `match`, etc.).
- Stdlib-only for core scripts.
- Everything that writes to the wiki goes through `wiki_repo.write_page` — no raw `git` shellouts outside that module.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
