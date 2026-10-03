# Wiring plainmem into an agent

Paste the block below into your `AGENTS.md` (Codex, and most agents that read it) or `CLAUDE.md` (Claude Code), then adjust the path.

```markdown
## Long-term memory

Notes live as Markdown in `~/notes`. They are the source of truth; `~/notes/.plainmem/` is a cache.

- Before answering from memory, search: `plainmem --root ~/notes search --json "<question>"`.
- Cite what you use as `path:line` from the `cite` field.
- A result with `status: SUPERSEDED` has been replaced. Use the entry listed in `superseded_by`.
- A result with `must_reverify: true` is a price, status or availability older than the window.
  Say the note exists and how old it is. Do not state the value as current without checking.
- You may not say "there is no record of X" unless you ran the search in this session and the
  JSON had `no_match: true`. Quote `searched_at` and `index_version` if asked.
- To remember something: `plainmem --root ~/notes add "<fact>"`. Write facts in the
  `Thing key: value` or `The thing is now value` shape so later changes are detected.
```

## MCP (Claude Code, Claude Desktop, Cursor and others)

Install with the MCP extra and register the server:

```bash
pip install "plainmem[mcp]"
claude mcp add plainmem -- plainmem-mcp --root ~/notes
```

The server exposes five tools: `search` (same JSON as the CLI, including `searched_at` and `no_match`; optional `as_of`), `explain` (current value, superseded values, timeline and provenance; optional `as_of`), `diff` (facts added or updated between two dates), `add` and `stale`. Keep the rules above in `CLAUDE.md` either way; the tool descriptions repeat the important ones, but a written rule in the project file is what the model sees every turn.

## Codex CLI

Codex reads `AGENTS.md` and can run shell commands, so the CLI lines above are enough. If you prefer MCP, add to `~/.codex/config.toml`:

```toml
[mcp_servers.plainmem]
command = "plainmem-mcp"
args = ["--root", "/Users/you/notes"]
```
