---
name: plainmem-memory
description: Use when answering from long-term notes, or when asked whether something was recorded. Searches Markdown memory with citations and freshness checks.
---

Search before answering from memory: call the `search` tool and cite results as `path:line`.

- `status: SUPERSEDED`: use the entry in `superseded_by`.
- `must_reverify: true`: say the note exists and how old it is. Do not state the value as current without checking.
- Only say "there is no record of X" after a `search` in this session returned `no_match: true`.
- To remember something, call `add` with a fact shaped like `Thing key: value` so later changes are detected.
- Before `add`, call `candidates` with the note. If the note says one of those facts now has a different value, pass that fact's `key` as `supersedes`. The note may name the fact by what its holder does (who gets paged, who approves purchases, where it runs) rather than by the key; a note saying who or what holds it now ("from now on", "these days") counts. Do not pick a key with a qualifier the note does not use (backup, replica, staging). If unsure, do not pass it: a note about what someone has been doing, might do, or did once is not a replacement.
- `stale` lists volatile facts past their re-verification window.
