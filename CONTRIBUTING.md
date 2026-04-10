# Contributing to llm-wiki

## Ways to contribute

- **Bug reports** — open an issue with steps to reproduce
- **Feature requests** — open an issue describing the use case
- **Pull requests** — bug fixes, new search channels, web UI improvements, new agent behaviors

## Development setup

```bash
git clone https://github.com/Oshayr/llm-wiki
cd llm-wiki

# Install core dependencies (web UI, MCP server)
pip install -r requirements.txt

# Optional: enhanced features
pip install sentence-transformers numpy scikit-learn   # semantic search
pip install trafilatura                                # fallback content extraction
```

Test a skill locally by installing the plugin into a Claude Code project:
```bash
claude plugin install ./
```

## Project structure

| Directory | Purpose |
|-----------|---------|
| `agents/` | Agent markdown specs (Claude reads these) |
| `bin/` | 23 Python utility scripts called by agents |
| `mcp/` | FastMCP server exposing wiki as MCP tools |
| `rules/` | Always-on behavioral rules |
| `skills/` | Slash-command skill definitions |
| `skills/serve/scripts/` | FastAPI web server + Jinja2 templates |

## Adding a search channel

1. Create `bin/search-<channel>.py` following the pattern in `bin/search-academic.py`
2. Add the channel to `CHANNEL_TTLS` in `bin/cache.py`
3. Add a `### <channel>` section to `agents/search-channel.md`
4. Add the channel to `agents/search-orchestrator.md`'s Fan Out list

## Code style

- Python 3.11+ syntax (`X | Y` unions, `match`, etc.)
- stdlib-only for core scripts; optional heavy deps (numpy, torch) imported lazily
- All search scripts output normalized JSON arrays to stdout

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
