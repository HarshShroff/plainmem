# Supersession benchmark (experimental)

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

## Pre-registered success criterion

Written and committed before the held-out run:

- **Success** = a substantial reduction in implicit-supersession stale answers (categories B, C, D: the `implicit_stale` rate falls to at most half of arm A's) **and** a false-supersession rate near zero, defined as **at most 1%** of the unrelated + ambiguous notes (categories E, F, G). With 38 such held-out notes, 1% means zero false tags.
- A large stale reduction with false supersession above 1% is reported as a **failure** for that arm, not as a partial success.
- The 36 held-out adversarial cases of `bench/temporal` are reported before and after for each arm. They were never used for tuning.
- Held-out is run once, after all dev changes. Any change made after it is listed with its effect.

## Metrics

See the docstring of `run.py`. Precision and recall count a tag as right only with the right target key. The abstention 2x2 splits true supersessions into detected / wrong target / abstained (`insufficient`) / rejected, and unrelated + ambiguous notes into rejected / abstained / falsely tagged. The agent arm can only pass a key or nothing, so it never abstains as such; "passed nothing" counts as rejected.
