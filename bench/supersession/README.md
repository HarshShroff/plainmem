# Supersession benchmark (experimental)

Two runs. Run 1 (seed 2026, files in `run1/`) had a labelling bug in its generator, described in `run1/README.md`. Run 2 (seed 4127) is a second attempt with the bug fixed, a fresh frozen held-out split and its own pre-registration below. Both are reported.

Question: can a write-path step link an update that does not repeat a fact's key ("Priya took over from Sam on Orion") to that fact (`Orion project lead`), without linking notes that only look similar? The read path is unchanged: `explain` stays deterministic and makes no model calls. The model is only consulted when a note is written, it only returns a verdict, and plainmem validates that verdict and writes the tag itself.

## Reproduce

```bash
python bench/supersession/generate.py --out /tmp/supersession          # inspect the data
python bench/supersession/run.py --split heldout --cache-only          # held-out tables from llm_cache.json, no model calls
python bench/supersession/run.py --split dev --no-write --show-failures 5
python bench/supersession/temporal_rerun.py --cache-only               # the 36 temporal adversarial cases
```

Without `--cache-only`, prompts missing from `llm_cache.json` are sent to `claude -p --model haiku` and logged in `llm_calls.jsonl`.

## Data

300 cases, seed 2026, one entity each, plus 60 entities with no case and 150 noise notes. Each entity file holds 4 to 6 facts, including the asked attribute (except G) and at least one other attribute of the same kind (another person, region, database ...), so the target is never the only plausible one. Notes go into `log.md` in date order.

| category | share | gold | example |
|---|---|---|---|
| A explicit | 12% | supersedes | "Dana is no longer the Orion project lead. Sam is." |
| B direct implicit | 16% | supersedes | "Sam took over from Dana on Orion." |
| C indirect implicit | 16% | supersedes | "Sam took over Orion." |
| D event-based | 14% | supersedes | "Orion changed hands after Dana left; Sam runs it now." |
| E unrelated but similar | 16% | unrelated | "Sam joined the Orion team." |
| F ambiguous | 14% | insufficient | "Sam has been running Orion lately." |
| G abstention | 12% | unrelated | like E, but the asked attribute was never recorded |

The held-out split is 30% of each category (`random.Random(seed + 1)`), frozen in `split.json` and committed before any system ran. Each (attribute, category) has several templates and the last is reserved for held-out cases, so about a third of the held-out set (31 of 90) uses wording no one tuned on.

The same person wrote the templates, the classifier prompt and the agent-simulation prompt. That is the main reason to distrust these numbers; the reserved wordings and the 36 temporal cases (written months earlier, for a different benchmark) are the partial check.

## Arms

- **A current plainmem**: plain `add`, no consolidation.
- **B agent-declared supersedes, simulated.** One model call plays a writing agent. It sees the skill file (`skills/plainmem-memory/SKILL.md`), the note, and the `candidates` tool output, nothing else: never the category, gold verdict or question. It returns the `supersedes` argument it would pass to `add`, or null. This is a simulation of an agent following the skill rule, not a measurement of any real agent.
- **C classifier**: the constrained JSON classifier (`consolidate_llm.py`) alone.
- **D agent, then classifier**: B; the classifier is asked only when the agent passed nothing.

B, C and D pass through the same validator before a tag is written (target among the candidates, still current, the note supplies a value, relation allowed). All model calls are `claude -p --model haiku`. A lexical heuristic was tried on dev (precision 0.70, recall 0.16, no false tags) and dropped.

## Run 1 pre-registered success criterion

Written and committed before the held-out run:

- **Success** = a substantial reduction in implicit-supersession stale answers (categories B, C, D: the `implicit_stale` rate falls to at most half of arm A's) **and** a false-supersession rate near zero, defined as **at most 1%** of the unrelated + ambiguous notes (categories E, F, G). With 38 such held-out notes, 1% means zero false tags.
- A large stale reduction with false supersession above 1% is reported as a **failure** for that arm, not as a partial success.
- The 36 held-out adversarial cases of `bench/temporal` are reported before and after for each arm. They were never used for tuning.
- Held-out is run once, after all dev changes. Any change made after it is listed with its effect.

## Metrics

See the docstring of `run.py`. Precision and recall count a tag as right only with the right target key. The abstention 2x2 splits true supersessions into detected / wrong target / abstained (`insufficient`) / rejected, and unrelated + ambiguous notes into rejected / abstained / falsely tagged. The agent arm can only pass a key or nothing, so it never abstains as such; "passed nothing" counts as rejected.

## Run 1 outcome (added after the held-out run)

The pre-registered criterion was not met by any arm. Implicit stale fell from 1.000 to 0.220 (B), 0.268 (C) and 0.171 (D), but each arm wrote 1 false tag on 38 unrelated or ambiguous notes (2.6%). It was the same note in all three ("BasaltStack keeps backups in us-west-2.", a held-out-only template). Arguably that is a generator labelling error, since the entity has a `Backup region` fact that the note does update. That reading is post-hoc, so the result stands as a fail. B and D also wrote 2 wrong-target tags on true updates. Full tables are in `results.md`; the tuning history is in `dev-rounds.md`.

## Run 2: what changed before any system ran

- **Generator audit.** Every negative template (E, F; G reuses E) was checked for a key collision with any attribute an entity can hold. Two changed: "{E} keeps backups in {new}." (updates `Backup region`, the run-1 bug) became "{E} hosts its status page in {new}."; "{E} exports a nightly dump to {new}." (arguably a `Replica database`) became "{E} wrote a {new} connector for a customer." Both replacements still name a value of the asked kind next to the entity, about an attribute no entity has, so the case stays as hard. No case was deleted.
- **Collision guard.** `generate.py` now refuses to generate if a must-not-supersede note touches an existing fact key of its entity other than the asked one, or a positive note touches a same-kind sibling. "Touches" = the note contains every cue word of the key (the key tokenised as plainmem tokenises keys, minus generic kind words such as region or provider) and its value has that key's kind. It runs at template level (`audit_templates`, any entity) and on the generated cases (`check_cases`). With the old template it fails on exactly the run-1 note. Tests: `tests/test_supersession_generate.py`.
- **Fresh split.** Seed 4127, case ids t0001..t0300 (run 1 used s0001..s0300, so no id can repeat), 30% held out per category, frozen in `split_v2.json` and committed before any model call. 90 held-out cases, 38 of them negatives (E 14, F 13, G 11), 31 with reserved wording.
- Run-1 cache, ledger and results are in `run1/`. Run 2 starts from an empty `llm_cache.json`.

## Run 2 pre-registered success criterion

Written and committed with `split_v2.json`, before any run-2 model call.

- **Success for an arm** = both of:
  1. implicit-supersession stale rate (categories B, C, D, `implicit_stale`) at most **half** of arm A's on held-out. Arm A is expected at 1.0, so the bar is <= 0.50.
  2. false-supersession rate **<= 1%** of held-out unrelated + ambiguous notes (E, F, G). With 38 such notes this means **zero** false tags.
- Reported for every arm, not part of the bar: precision, recall, wrong-target tags, the abstention 2x2, stale rate on A-D, the 36 `bench/temporal` held-out adversarial cases before and after.
- Missing either part is a fail for that arm, not a partial success.
- Default recommendation rule, fixed now: classifier-only (C) is recommended as the default only if C meets the bar. Among arms that meet it, prefer fewer wrong tags (false + wrong-target), then lower implicit stale. If no arm meets it, no consolidation arm is recommended as a default.
- Tuning (prompt wording, validator, candidate retrieval) uses the dev split only, logged in `dev-rounds-v2.md`. Held-out is run once, after the configuration is frozen. Total model calls, dev included, are capped at about 1,500 and reported.

## Run 2 outcome (added after the held-out run)

Held-out was run once, on the configuration frozen in commit a0e7f70. **C (classifier alone) meets the bar**: implicit stale 1.000 -> 0.073, 0 false tags out of 38, precision 1.000, recall 0.942, no wrong-target tags. **B and D fail**: each wrote 1 false tag, the same ambiguous note ("Bram Garside has been running QuillPeak lately.", filed by the simulated agent as `Project lead`), although D had implicit stale 0.000 and recall 1.000. Temporal 36 stale counts: A 36, B 4, C 4, D 1, with no tags on the 25 noise lines. Full tables: `results.md` (cache-only outputs, so `--cache-only` reproduces them byte for byte); dev history: `dev-rounds-v2.md`. Model calls for run 2: 1,395 (`llm_calls.jsonl`).
