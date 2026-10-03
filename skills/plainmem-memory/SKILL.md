---
name: plainmem-memory
description: Use when answering from long-term notes, or when asked whether something was recorded. Searches Markdown memory with citations and freshness checks.
---

Search before answering from memory: call the `search` tool and cite results as `path:line`.

- `status: SUPERSEDED`: use the entry in `superseded_by`.
- `must_reverify: true`: say the note exists and how old it is. Do not state the value as current without checking.
- Only say "there is no record of X" after a `search` in this session returned `no_match: true`.
- To remember something, call `add` with a fact shaped like `Thing key: value` so later changes are detected.
- Before `add`, call `candidates` with the note. If the note replaces one of those facts, pass that fact's `key` as `supersedes`. If unsure, do not pass it.
- `stale` lists volatile facts past their re-verification window.
