# plainmem

plainmem: durable memory for coding agents, stored as plain text. It tracks when memories become stale or are superseded, so agents avoid confidently using outdated information.

Agents that keep notes across sessions tend to fail in two quiet ways: they repeat a fact that stopped being true months ago, and they say "I have no record of that" without having looked. plainmem is a small, dependency-free memory layer over plain Markdown files that ranks what it finds, tells you how old each fact is, notices when a newer note contradicts an older one, and returns proof that a search actually ran.

Live demo: https://plainmem.streamlit.app/

```
$ plainmem --root examples/notes --now 2026-10-03 search -k 3 who is the orion project lead
searched 2 files / 7 chunks (index dd212fe8308e, 2026-10-03T14:59:17+00:00)

log.md:5  [FRESH, 50d]
  Log > 2026-08-14
  - Orion project lead: Sam Okafor, Dana moved to Atlas.

orion.md:8  [SUPERSEDED, 335d] superseded by log.md:5
  Orion > People
  - Project lead: Dana Whit

orion.md:9  [STALE, 335d] must re-verify before asserting
  Orion > People
  - Budget: $40,000
```

## Quickstart

```bash
pip install -e .                      # Python 3.10+, no third-party dependencies
plainmem --root ~/notes index         # builds ~/notes/.plainmem/index.json (a cache)
plainmem --root ~/notes search "gym day pass price"
plainmem --root ~/notes search --json "dentist phone"    # for agents
plainmem --root ~/notes add "Orion project lead: Sam Okafor"
plainmem --root ~/notes explain "who is the orion project lead"   # current value, superseded values, timeline
plainmem --root ~/notes explain --as-of 2026-06-01 "who is the orion project lead"   # what was true then
plainmem --root ~/notes search --as-of 2026-06-01 "orion project lead"   # the notes as they stood then
plainmem --root ~/notes diff --since 2026-09-01   # facts added or updated since a date
plainmem --root ~/notes conflicts     # facts with more than one value, newest first
plainmem --root ~/notes stale         # volatile facts past their re-check window
plainmem --root ~/notes stats
plainmem --root ~/notes rotate --keep-days 14   # move old log days to archive/, verbatim
```

From Python:

```python
from datetime import date
from plainmem import Memory

mem = Memory("~/notes")
resp = mem.search("orion project lead")
resp.no_match, resp.searched_at, resp.index_version
[(h.chunk.cite, h.status, h.must_reverify) for h in resp.hits]
mem.explain("who is the orion project lead", as_of=date(2026, 6, 1))["fact"]["current"]
```

### Wiring it into Claude Code or Codex

Paste this into `CLAUDE.md` (Claude Code) or `AGENTS.md` (Codex) and change the path:

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
  End the line with `{explicit, user}` if the user told you, `{observed, tool}` if you read it
  from a tool, `{inferred, agent}` if you concluded it yourself.
```

MCP setup for Claude Code (`claude mcp add`) and Codex (`config.toml`) is in [examples/AGENTS-snippet.md](examples/AGENTS-snippet.md). The MCP server (`plainmem-mcp`) needs `pip install "plainmem[mcp]"`; the core never imports it.

## Design

```
  your notes (*.md, the source of truth)             agent / CLI / MCP
        |                                                   |
        v                                                   v
  parse: chunks with path:line, heading path,      search / explain / diff
  dates, trailing {tags}                            (optional --as-of DATE)
        |                                                   |
        v                                                   |
  facts: key: value and "X is now Y" lines  --->  supersession by key, newest
  with authority, source, from, until             wins; authority breaks
        |                                         same-date ties; until expires
        v                                                   |
  .plainmem/index.json (disposable cache)  --->  BM25 (+ optional embeddings,
                                                  RRF) -> decay, demote
                                                  superseded -> cited answer
```

### Markdown is the source of truth

Your notes stay as `.md` files you can open, edit, grep, diff and commit. The index under `.plainmem/` is a JSON cache of parsed chunks and tokens. You can delete it at any time and `plainmem index` rebuilds it. Re-indexing is incremental: a file whose mtime and size are unchanged is reused, and a file that was only touched (same SHA-1) is reused too.

Because the index is disposable, it fails closed. A truncated file, a hand edit, a checksum mismatch or a schema change raises `IndexCorruptError` (exit code 3 on the CLI) instead of quietly serving partial results. `plainmem index --rebuild` fixes it, and your Markdown is never touched.

### Chunks you can cite

Each paragraph, list item, table row and fenced code block is a chunk. A chunk keeps its line range and the heading path above it, so every result is citable as `path:line` and the headings are searchable ("Orion > People" makes "Project lead: Dana" findable by "orion lead"). Retrieval is Okapi BM25 over stemmed tokens, with a stdlib Porter stemmer and a stopword list, so "relocate" finds "relocating".

### Freshness

Every chunk gets a date from the most specific source available: an inline `[verified: 2026-05-01]` tag, a dated heading above it (`## 2026-03-14`, which is how logs are written), front matter `verified:`, `updated:` or `date:`, and finally the file's mtime. Results are labelled FRESH (up to 90 days), AGING (up to a year) or STALE, with the age in days.

Some facts rot faster than others. A chunk is volatile if it is tagged `[volatile]`, sits in a file with `volatile: true`, or matches a short list of patterns: prices and currency amounts, "currently", "as of", opening hours, `Status:`, availability and stock. A volatile fact older than the window (30 days by default, `--volatile-days`) is marked `must_reverify`. The intended agent behaviour is to say the note exists and how old it is, and to not assert the value as current.

The full ranker multiplies the BM25 score by `0.75 + 0.25 * 0.5^(age / 180 days)`, so age breaks near-ties and nothing else. All of these numbers are in `FreshnessConfig` and `RankConfig`.

### Supersession

When two chunks assert different values for the same key, the one with the newer date wins and the older one is marked SUPERSEDED. Two shapes are recognised, one per line or sentence:

- `key: value`, e.g. `- Orion project lead: Sam Okafor`
- `X is Y`, `X is now Y`, `X moved to Y`, `X changed to Y`, e.g. `The Orion designer is now Kai Moss.`

Keys are compared as sets of stemmed words. Outside dated log sections, a key that does not already name the file's subject is qualified with it (front matter `entity:`, else the H1 title), so `Status: paused` in `orion.md` and in `atlas.md` stay separate, while `Project lead: Dana` in `orion.md` and `Orion project lead: Sam` in a log collide as intended. In search results the current version is placed first and its superseded versions directly under it, so an agent sees both the answer and the history. Two different values with the same date are reported by `plainmem conflicts` as unresolved and neither is demoted.

### Metadata tags

A fact line can end in an optional tag in braces. It is plain text, so the file still reads fine without plainmem, and a line without one behaves exactly as before:

```markdown
- Orion project lead: Sam Okafor {explicit, user}
- Orion deploy region: eu-west-2 {observed, tool, from 2026-09-18}
- Orion release freeze: on {explicit, user, until 2026-09-30}
- Priya took over from Sam on Orion {explicit, user, supersedes Orion project lead}
```

Items are comma separated, in any order, each at most once:

| item | values | meaning |
|---|---|---|
| authority | `explicit`, `observed`, `inferred`, `imported` | a person said it; read from a tool or system; an agent concluded it; copied from another document |
| source | `user`, `tool`, `agent`, `document` | who or what it came from |
| `from YYYY-MM-DD` | date | true from this date (default: the line's own date) |
| `until YYYY-MM-DD` | date | true up to and including this date; after it the fact is EXPIRED |
| `supersedes <key>` | key words | this line replaces the current value of that key, for updates whose wording doesn't repeat the key |

The vocabulary is fixed on purpose. Authority is a category, not a confidence number, and it only does two things. On the same date it breaks a tie (explicit, then observed, then imported, then inferred), but only when every rival line is tagged. And an `inferred` value never silently replaces an `explicit` one: the conflict is reported as unresolved (`unresolved_reason: "inferred-over-explicit"`) and nothing is demoted. A brace group containing anything outside the vocabulary is ordinary text, so `{name}` in prose is left alone. In a dated log section, name the entity in `supersedes` the same way you would in the line itself (`supersedes Orion project lead`).

Search results, `explain`, `diff`, `--json` and the MCP tools all carry `authority`, `source`, `valid_from` and `valid_until` (null when a line is untagged). Search results also list every fact in the chunk under `facts`.

### Explain and diff

`plainmem explain` takes a question, runs the normal search, and follows the fact whose key shares the most words with the question (ties go to the higher-ranked hit). It prints the current value, the values it replaced, and a timeline, each with a `path:line` cite and date, plus the freshness of the current value. Against `examples/notes`:

```
$ plainmem --root examples/notes --now 2026-10-03 explain "Who is the Orion project lead?"
Orion project lead
  current     Sam Okafor  (log.md:5, 2026-08-14)
  superseded  Dana Whit  (orion.md:8, 2025-11-02)
  freshness   FRESH, 50d old
  timeline
    Dana Whit: 2025-11-02 -> 2026-08-14
    Sam Okafor: 2026-08-14 -> present

$ plainmem --root examples/notes --now 2026-10-03 explain "what is the orion deploy region"
Orion deploy region
  current     eu-west-2  (log.md:9, 2026-09-18; observed, tool, from 2026-09-18)
  superseded  us-east-1  (orion.md:10, 2025-11-02)
  freshness   FRESH, 11d old
  timeline
    us-east-1: 2025-11-02 -> 2026-09-18
    eu-west-2: 2026-09-18 -> present

$ plainmem --root examples/notes --now 2026-10-03 explain "is the orion release freeze on"
Orion release freeze
  current     on  (log.md:10, 2026-09-22; explicit, user, until 2026-09-30)  (EXPIRED)
  freshness   FRESH, 11d old
```

(The `searched ...` header line is left out of these examples.)

If the search finds nothing it prints `no match` and exits 1; `--json` adds `searched_at`, `index_version` and `no_match` as `search` does. If chunks match but none states a fact about the question, `no_fact` is true and `nearest` lists the cites. The same call is `Memory.explain(question)` and the `explain` MCP tool.

`plainmem diff --since DATE [--until DATE]` lists facts that appeared (a new key) or changed value (`old -> new`) in a window, by the same entry dates:

```
$ plainmem --root examples/notes --now 2026-10-03 diff --since 2026-01-01
changes since 2026-01-01
  ADDED    Orion release freeze: on  (log.md:10, 2026-09-22; explicit, user, until 2026-09-30)
  UPDATED  Orion project lead: Dana Whit (orion.md:8, 2025-11-02) -> Sam Okafor (log.md:5, 2026-08-14)
  UPDATED  Orion deploy region: us-east-1 (orion.md:10, 2025-11-02) -> eu-west-2 (log.md:9, 2026-09-18; observed, tool, from 2026-09-18)
```

Both ends of the window are inclusive. An updated fact is compared against its last value before `--since`, so several changes inside the window show as one row. It is `Memory.diff(since, until)` in Python, and `--json` returns `added` and `updated` lists.

### As of a date

`--as-of DATE` on `search` and `explain` (and `as_of=` in `Memory.search`, `Memory.explain` and the MCP tools) answers what was true on that date. Notes known to be written or to take effect later are dropped, supersession is recomputed from the facts in effect by then, `until` dates are applied, and ages are measured from that date. The date in the question is a filter, so it is not matched as words.

```
$ plainmem --root examples/notes --now 2026-10-03 explain --as-of 2026-09-01 "what is the orion deploy region"
Deploy region  (as of 2026-09-01)
  value then  us-east-1  (orion.md:10, 2025-11-02)
  later       eu-west-2  (log.md:9, 2026-09-18; observed, tool, from 2026-09-18)
  freshness   AGING, 303d old
  timeline
    us-east-1: 2025-11-02 -> 2026-09-18
    eu-west-2: 2026-09-18 -> present

$ plainmem --root examples/notes --now 2026-10-03 explain --as-of 2025-06-01 "what is the orion deploy region"
Orion deploy region  (as of 2025-06-01)
  NONE  nothing recorded by then
```

Unknown dates are not guessed. A date that only comes from file mtime says when a file was saved, not when a fact became true, so an as-of answer resting on one has `status: "uncertain"`, and a date before every saved file gives `"unknown"`. The full set is `known`, `uncertain`, `expired`, `none` and `unknown`.

### Hybrid retrieval (optional)

`--mode hybrid` (and `Memory(..., embed=fn)` / `mode="hybrid"`) fuses BM25 with sentence-embedding similarity by reciprocal-rank fusion, then runs the same decay, supersession, expiry and as-of layer. It needs `pip install "plainmem[embeddings]"`; the core never imports it and the vectors are kept in memory only. It has unit tests with a stub embedder but has not been benchmarked yet; see below.

### The absence rule

`plainmem search --json` always returns `searched_at`, `index_version`, `files_indexed`, `chunks_indexed` and a `no_match` boolean. The point is a rule you can put in an agent's instructions and check: it may not claim "there is no record of X" unless it ran the search in this session and got `no_match: true`. An agent that answers from its context window instead of searching is the most common way memory systems fail in practice, and a field you can audit is harder to skip than a sentence in a prompt. The CLI exits 1 on no match, so shell wrappers can enforce the same thing.

### Writing

`plainmem add` appends a bullet under today's `## YYYY-MM-DD` heading in `log.md`. Writers take an atomic `mkdir` lock (either the directory is created or the call fails, so two processes can't both win), and a lock left behind by a crashed writer is broken after 60 seconds. `plainmem rotate` moves whole dated sections older than N days to `archive/log-YYYY-MM.md`. The archive is written and fsynced before the log is rewritten, and a section already in the archive is not appended again, so a crash at any point loses nothing and duplicates nothing. The tests run six processes appending 25 entries each and check every entry lands exactly once.

## Temporal benchmark

The question this benchmark is built to answer, and able to answer "no": do explicit time and provenance semantics cut stale answers more than better retrieval does?

`bench/temporal/generate.py` builds a deterministic corpus (seed 2026) of project notes plus quarterly logs, with ten kinds of question: a single update, several sequential updates, two contradictory values on the same day (one `{explicit, user}`, one `{inferred, agent}`), look-alike distractor facts, facts that never change, "right now" questions, "what was it on date T" questions (a third of them back-dated with `from`), provenance questions, adversarial updates whose wording shares nothing with the key ("Priya took over from Sam on Orion"), and paraphrased questions. A 30% held-out split, stratified by category, was frozen in `bench/temporal/split.json` before any system ran. Two fixes were made while looking only at dev failures (fact picking by key overlap, and not matching the as-of date as words); the held-out set was run once after that. The full output is in [bench/temporal/results.md](bench/temporal/results.md), and the analysis and caveats are in [bench/temporal/README.md](bench/temporal/README.md).

This is a purpose-built benchmark, not a standard public memory benchmark. Its goal is to isolate temporal supersession and provenance, not to claim broad memory-system superiority. The generator and the frozen split are in the repo so anyone can rerun or extend it.

It scores four separate things, because a system can do well on one and badly on another:

- **Retrieval** (recall@1, recall@5): did the right line come back at all?
- **Current-state answering**: is the answer what is true now? The stale-answer rate is how often a superseded value was given as current.
- **Historical answering** (as-of): is the answer what was true on a given date?
- **Provenance**: does the answer cite the right line and source?

Held-out split, 1,000-case corpus (300 held-out questions, 1,203 files, 9,013 chunks):

| system | recall@1 | recall@5 | current-state acc | stale-answer rate | as-of acc | provenance acc | median ms |
|---|---|---|---|---|---|---|---|
| bm25-raw | 0.123 | 0.847 | 0.105 | 0.825 | 0.310 | 0.000 | 0.31 |
| bm25 (stemmed) | 0.123 | 0.853 | 0.105 | 0.825 | 0.310 | 0.000 | 0.32 |
| plainmem search (top hit) | 0.690 | 0.833 | 0.759 | 0.158 | 0.095 | 1.000 | 5.10 |
| plainmem explain | 0.793 | 0.900 | 0.763 | 0.158 | 1.000 | 1.000 | 6.57 |
| plainmem explain + embeddings (hybrid) | 0.780 | 0.883 | 0.820 | 0.158 | 0.929 | 1.000 | 93.68 |

The finding: in this benchmark, better retrieval did not reduce stale answers, and explicit temporal state did. BM25 and plainmem retrieve the right line about equally often (recall@5 0.853 against 0.900), but the stale-answer rate falls from 0.825 to 0.158 once supersession is tracked. Stemming moved the stale rate by nothing. Adding embeddings didn't move it either:

| | lexical | + embeddings |
|---|---|---|
| current-state acc | 0.763 | 0.820 |
| stale-answer rate | 0.158 | 0.158 |
| as-of acc | 1.000 | 0.929 |
| median latency | 7 ms | 94 ms |

Embeddings do help. They fixed most paraphrased questions (0 of 18 correct to 14 of 18), which is where the current-state gain comes from. They cost as-of accuracy, because the embedding candidates push some dated lines out of the top five, and they are about 13 times slower. The accurate summary is that embeddings improved retrieval but did not reduce the stale-answer rate here. This is one embedding model (all-MiniLM-L6-v2) with untuned fusion, so treat it as one data point.

Where it breaks: every remaining stale answer, 36 of 36, is an adversarial update, one worded with nothing in common with the fact it replaces ("Priya took over from Sam on Orion" against "Orion project lead: Sam"). Neither lexical nor embedding retrieval links the two: in 24 of the 36 the update isn't retrieved at all, with or without embeddings, and in the other 12 it is retrieved but nothing ties it to the old fact. An explicit `supersedes` tag fixes it when someone writes one; nothing infers it from prose. That boundary, explicit supersession works and implicit change doesn't yet, is the open problem.

Some wins exist by construction: contradictory questions are only solvable through the authority tag, provenance questions reward returning a citation, and back-dated as-of questions need the `from` tag. BM25 never had a chance on those, so they show the tags work as specified, not that they are a good idea. How the next step was chosen (the pre-agreed recall@5 rule, applied on dev) and the per-category tables are in [bench/temporal/README.md](bench/temporal/README.md) and [bench/temporal/results.md](bench/temporal/results.md). Reproduce, including the hybrid row: `pip install -e ".[embeddings]" && python bench/temporal/run.py`.

## Retrieval benchmark

`python bench/run.py` generates a synthetic corpus and labelled queries, then scores six systems. Everything below is the actual output of that run on an Apple Silicon laptop, CPU only.

The corpus and the labels are written by the same author as the ranker. They are synthetic and deterministic (seed 7), and this is not an independent benchmark. Two of the four query types test behaviour that only plainmem implements (supersession and staleness flags), so its lead on those rows exists by construction. The lookup and paraphrase rows are the fair comparison.

- Corpus: 426 Markdown files (130 contacts, 59 projects, 40 places, 157 journal days, 40 misc notes), 2,721 chunks, reference date 2026-09-29.
- 158 queries: 40 lookup (the query reuses the fact's words), 42 paraphrase (author-written rewordings), 36 superseded (a later journal entry changes a project lead, designer or someone's company; the correct answer is the newer note), 40 staleness (price or opening hours of a place; 24 are past the 30-day window and must be flagged, 16 are fresh controls that must not be).
- Systems: `grep` counts distinct query words present in each chunk (substring, case-insensitive, stopwords removed, headings not visible, like grepping lines). `bm25-raw` is BM25 without stemming. `bm25` is plainmem with `mode="bm25"`. `plainmem` is the full ranker. `embed` is sentence-transformers `all-MiniLM-L6-v2` cosine similarity over heading path plus chunk text. `embed+layer` takes the embedding top 50 and re-ranks it with plainmem's freshness and supersession layer (`Engine.rerank`).
- Metrics: recall@1 and @5 and MRR against the labelled line. Stale-answer rate: share of superseded queries whose top result is the outdated fact. False-fresh rate: share of past-window staleness queries where the fact is in the top 5 without a re-verify flag. Over-flag rate: the same for fresh controls that were wrongly flagged. Systems with no notion of freshness can't flag anything, so their false-fresh rate equals how often they found the fact.

| system | R@1 | R@5 | MRR | stale-answer rate | false-fresh rate | over-flag rate | p50 ms | p99 ms |
|---|---|---|---|---|---|---|---|---|
| grep | 0.392 | 0.589 | 0.468 | 0.000 | 0.708 | 0.000 | 0.68 | 1.03 |
| bm25-raw | 0.582 | 0.785 | 0.698 | 1.000 | 1.000 | 0.000 | 0.05 | 0.12 |
| bm25 | 0.658 | 0.854 | 0.766 | 1.000 | 1.000 | 0.000 | 0.05 | 0.11 |
| plainmem | 0.848 | 0.899 | 0.876 | 0.000 | 0.000 | 0.000 | 0.91 | 2.27 |
| embed | 0.791 | 0.886 | 0.844 | 0.472 | 1.000 | 0.000 | 2.98 | 5.05 |
| embed+layer | 0.867 | 0.994 | 0.909 | 0.000 | 0.000 | 0.000 | 3.42 | 3.80 |

Recall@1 by query type:

| system | lookup | paraphrase | stale | superseded |
|---|---|---|---|---|
| grep | 0.425 | 0.095 | 0.125 | 1.000 |
| bm25-raw | 0.975 | 0.310 | 1.000 | 0.000 |
| bm25 | 1.000 | 0.571 | 1.000 | 0.000 |
| plainmem | 1.000 | 0.548 | 0.975 | 0.889 |
| embed | 0.975 | 0.976 | 1.000 | 0.139 |
| embed+layer | 0.975 | 0.952 | 0.975 | 0.528 |

plainmem index: built in 0.09 s, loaded in 0.04 s, 712 KiB on disk. `conflicts` found 36 keys, which is exactly the 36 planted changes. The embedding baseline took 2.0 s to encode on CPU and holds 4 MiB of vectors in memory.

What the numbers say:

- On paraphrased questions the embedding model is far better: 0.976 recall@1 against 0.548 for plainmem. BM25 can't connect "where does she live" to "Lives in Fenby" beyond the name. If your agent asks questions in words your notes don't use, you want embeddings.
- Plain BM25, stemmed or not, returned the outdated fact first on every one of the 36 superseded queries. The older notes sit in files whose headings name the entity, which BM25 rewards. The embedding model returned the outdated fact first on 47% of them.
- grep's perfect superseded score is an artifact. It can't see headings, the old fact line (`- Company: Kestrel Labs`) doesn't contain the person's name, and the new journal line does. It never found the old fact at all, and it finds little else either.
- The freshness layer isn't free. Time decay cost plainmem one paraphrase query and one staleness query that plain stemmed BM25 got right, both times by lifting a newer note about a similar place or person above the correct older one. Four superseded queries still fail because another short chunk in the same contact file outranks the new journal line.
- The layer composes with embeddings: `embed+layer` has the best recall@1 and recall@5 overall and a zero stale-answer rate. Supersession recall@1 is still only 0.528 there, because the promotion step only reorders what the first stage retrieved.
- plainmem is about 18 times slower per query than bare BM25 (0.9 ms against 0.05 ms p50) because it computes freshness for every candidate. At this corpus size that doesn't matter; at a few million chunks it would.

Reproduce: `pip install -e ".[dev,embeddings]" && python bench/run.py` (drop `embeddings` and add `--no-embed` to skip the model download).

## Limitations

- The benchmark is synthetic and self-labelled, as described above. Real notes are messier, and the paraphrase templates are only as varied as one author made them.
- The core has no semantic understanding. It matches words and word stems. Use the embedding numbers above to decide whether that is enough for you.
- Supersession is pattern based. It only sees `key: value` lines and a handful of "X is now Y" verbs, only compares values as normalised strings, and it can be fooled: "Dana is out today" and "Dana is back" become a conflict about Dana. Keys that differ by a word ("lead" vs "owner") are not linked. A same-day disagreement is flagged but not resolved.
- Metadata tags have to be written. Nothing infers authority, source, validity dates or a `supersedes` link from prose, and an update worded without the key's words is missed (see the adversarial row above).
- Hybrid retrieval is benchmarked once, with one embedding model and untuned fusion settings. It helps paraphrase and hurts as-of recall and latency; see the temporal benchmark notes.
- `explain` and `diff` read the same extracted facts, so they inherit those limits. A timeline "from" date is the date the value was recorded or last verified (a front matter `verified:` date, for instance), not when it became true. A fact with no recoverable date is shown with `?` in `explain` and skipped by `diff` (counted in `undated_skipped`). `explain` follows one key: when a key is a same-day list, it reports the line the search ranked first and does not merge the values. `explain` only answers from keys that share a word with the question, so a paraphrase that shares none returns `no_fact` or, when only the entity name matches, a different fact about the same entity.
- The volatile detector is a list of regular expressions. It will miss volatile facts phrased some other way and occasionally flag a budget or a quoted price that is historical. Tag facts explicitly with `[volatile]` or `[verified: date]` when it matters.
- Dates come from what you write. A note with no tag, no dated heading and no front matter falls back to file mtime, which a `git clone` resets.
- The index is one JSON file loaded into memory. That is fine for tens of thousands of notes, not for millions.
- The MCP server was checked over stdio against MCP Python SDK 2.2.0 (initialize, list tools, call search). The 1.x `FastMCP` import path is kept as a fallback but untested, and I have not run it inside every MCP client.

## Related projects

Agent memory is a busy space. The projects below are the closest ones I found, described only by what their own READMEs say (checked 2026-09-29).

- [tigerless-labs/agent-memory](https://github.com/tigerless-labs/agent-memory) keeps Markdown files as the single source of truth with a SQLite index beside them that can be deleted at any time, and returns ranked file paths rather than pasted text.
- [okf-memory/okf-agent-memory](https://github.com/okf-memory/okf-agent-memory) is a Go library and CLI for Markdown and YAML memory in the OKF format, with in-memory BM25 retrieval and an MCP server.
- [kage-core/Kage](https://github.com/kage-core/Kage) keeps memory as plain Markdown in the repo, verifies memories against the actual code, and reports its own recall and stale-served numbers.
- [basicmachines-co/basic-memory](https://github.com/basicmachines-co/basic-memory) stores knowledge as local Markdown that both people and AI edit, builds a graph from wikilinks, and offers semantic and hybrid search over MCP.
- [aru-labs/lossless-memory](https://github.com/aru-labs/lossless-memory) never summarises: raw JSONL logs are the source of truth, with timestamped SQLite FTS5 and sqlite-vec indexes that can be rebuilt from them.
- [yantrikos/yantrikdb-server](https://github.com/yantrikos/yantrikdb-server) is a memory database that consolidates duplicates, detects contradictions and decays relevance over time, available as a Rust library, MCP server or HTTP cluster.
- [andrew-dev-p/memory-freshness-lab](https://github.com/andrew-dev-p/memory-freshness-lab) is an evaluation harness for stale cross-session memory that scores returned facts against a versioned timeline at an observation time.
- [plur-ai/plur](https://github.com/plur-ai/plur) (TypeScript, Apache-2.0) is local-first memory for agents, kept as plain YAML under `~/.plur` with an optional SQLite index. Its unit is the "engram", a typed assertion. It retrieves with BM25 plus BGE-small embeddings fused by reciprocal-rank fusion, decays activation ACT-R style, syncs over git and ships an MCP server. Its schema already has `supersedes`/`superseded_by` links, `valid_from`/`valid_until` validity dates with expired engrams left out of recall, provenance records, and an on-demand contradiction scan. I did not find a point-in-time (as-of) recall query, and its README lists contradiction and decay accuracy benchmarks as still in progress (checked 2026-10-03, README and source).
- [HUST-AI-HYZ/MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench) is a benchmark for agent memory covering accurate retrieval, test-time learning, long-range understanding and conflict resolution.

What this one does differently is narrow. Several of the projects above, PLUR in particular, already model supersession, validity dates and provenance; plainmem's version keeps all of it as a few words at the end of an ordinary Markdown line, answers "what was true on date T" directly, and comes with a held-out benchmark that measures stale answers against BM25. It is a single stdlib-only Python package you can read in an afternoon, and it treats time as part of every answer: each result carries its age, a FRESH/AGING/STALE status, a re-verify flag for volatile facts, and a pointer to whatever superseded it, and every search returns the fields an agent needs to prove it looked before claiming something isn't there. It does less than most of the projects above (no graph, no consolidation, no embeddings in the core), and the benchmark in this repo is small and self-made. If you need semantic recall, pair the freshness layer with an embedding retriever, as the `embed+layer` row does.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]" streamlit
pytest -q            # 239 tests
ruff check . && ruff format --check .
python bench/run.py --no-embed
python bench/temporal/run.py
streamlit run demo/app.py
```

MIT licensed. Written by Harsh Shroff.

## Privacy

plainmem runs locally. It reads the Markdown files under the folder you point it at, writes its index cache to `.plainmem/` inside that folder, and appends to `log.md` there when you call `add`. It makes no network calls and collects no telemetry. The Claude plugin installs it from PyPI with `uvx` the first time the MCP server starts; that download is the only network access.
