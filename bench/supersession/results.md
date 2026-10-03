# Supersession benchmark results, run 2

Run 1 (seed 2026, generator labelling bug) is archived in `run1/`; see `run1/README.md`.

Reproduce (no model calls, replies come from `llm_cache.json`):

```bash
python bench/supersession/run.py --split heldout --cache-only
python bench/supersession/temporal_rerun.py --cache-only
python bench/supersession/report.py
```

Held-out split, 90 of 300 cases (31 with reserved wording), seed 4127, ids t0001..t0300, frozen in
`split_v2.json` before any model call, run once after dev tuning (`dev-rounds-v2.md`).
Arm B is a simulated writing agent (one model call that sees the skill file, the note and the
`candidates` output), not a measurement of a real agent. All model calls: `claude -p --model haiku`.
Pre-registered bar (README.md): implicit stale at most half of arm A's, and false supersession at most
1% of unrelated + ambiguous notes (here 0 of 38).

## Pre-registered criterion, held-out

- B agent-declared (simulated): implicit stale 1.0 -> 0.073, false supersession 0.026 (1 tags): **fail**
- C classifier: implicit stale 1.0 -> 0.073, false supersession 0.0 (0 tags): **pass**
- D agent, then classifier: implicit stale 1.0 -> 0.0, false supersession 0.026 (1 tags): **fail**

## Split: heldout (90 cases)

| arm | precision | recall | false_supersession | abstention_rate | stale_rate | implicit_stale | current_acc | g_abstained | tags_written | wrong_target |
|---|---|---|---|---|---|---|---|---|---|---|
| A current plainmem | n/a | 0.0 | 0.0 | n/a | 1.0 | 1.0 | 0.342 | 0.0 | 0 | 0 |
| B agent-declared (simulated) | 0.98 | 0.942 | 0.026 | 0.0 | 0.058 | 0.073 | 0.861 | 0.0 | 50 | 0 |
| C classifier | 1.0 | 0.942 | 0.0 | 0.256 | 0.058 | 0.073 | 0.886 | 0.0 | 49 | 0 |
| D agent, then classifier | 0.981 | 1.0 | 0.026 | 0.244 | 0.0 | 0.0 | 0.899 | 0.0 | 53 | 0 |

Abstention 2x2 (true supersessions: detected / wrong target / abstained / rejected; unrelated+ambiguous: rejected / abstained / falsely tagged):

| arm | detected | wrong target | abstained | rejected | | rejected | abstained | falsely tagged |
|---|---|---|---|---|---|---|---|---|
| A current plainmem | 0 | 0 | 0 | 52 | | 38 | 0 | 0 |
| B agent-declared (simulated) | 49 | 0 | 0 | 3 | | 37 | 0 | 1 |
| C classifier | 49 | 0 | 0 | 3 | | 15 | 23 | 0 |
| D agent, then classifier | 52 | 0 | 0 | 0 | | 15 | 22 | 1 |

**A current plainmem**, by category

| category | n | tags | right target | current_acc | stale | outcomes |
|---|---|---|---|---|---|---|
| A explicit | 11 | 0 | 0.0 | 0.0 | 1.0 | stale 11 |
| B direct implicit | 14 | 0 | 0.0 | 0.0 | 1.0 | stale 14 |
| C indirect implicit | 14 | 0 | 0.0 | 0.0 | 1.0 | stale 14 |
| D event-based | 13 | 0 | 0.0 | 0.0 | 1.0 | stale 13 |
| E unrelated but similar | 14 | 0 | n/a | 1.0 | n/a | correct 14 |
| F ambiguous | 13 | 0 | n/a | 1.0 | n/a | correct 13 |
| G abstention | 11 | 0 | n/a | n/a | n/a | answered_other 11 |

**B agent-declared (simulated)**, by category

| category | n | tags | right target | current_acc | stale | outcomes |
|---|---|---|---|---|---|---|
| A explicit | 11 | 11 | 1.0 | 0.727 | 0.0 | correct 8, wrong 3 |
| B direct implicit | 14 | 14 | 1.0 | 0.857 | 0.0 | correct 12, wrong 2 |
| C indirect implicit | 14 | 11 | 0.786 | 0.714 | 0.214 | correct 10, stale 3, wrong 1 |
| D event-based | 13 | 13 | 1.0 | 0.923 | 0.0 | correct 12, wrong 1 |
| E unrelated but similar | 14 | 0 | n/a | 1.0 | n/a | correct 14 |
| F ambiguous | 13 | 1 | n/a | 0.923 | n/a | correct 12, overridden 1 |
| G abstention | 11 | 0 | n/a | n/a | n/a | answered_other 11 |

By wording: reserved (n=31): precision 1.0, recall 0.947, false supersession 0.0; seen (n=59): precision 0.969, recall 0.939, false supersession 0.038
Verdicts (gold -> validated): insufficient -> supersedes 1, insufficient -> unrelated 12, supersedes -> supersedes 49, supersedes -> unrelated 3, unrelated -> unrelated 25
Failed validator checks: none; decided by: {'agent': 90}; gold key among candidates: 1.0

**C classifier**, by category

| category | n | tags | right target | current_acc | stale | outcomes |
|---|---|---|---|---|---|---|
| A explicit | 11 | 11 | 1.0 | 0.727 | 0.0 | correct 8, wrong 3 |
| B direct implicit | 14 | 14 | 1.0 | 0.857 | 0.0 | correct 12, wrong 2 |
| C indirect implicit | 14 | 12 | 0.857 | 0.857 | 0.143 | correct 12, stale 2 |
| D event-based | 13 | 12 | 0.923 | 0.846 | 0.077 | correct 11, stale 1, wrong 1 |
| E unrelated but similar | 14 | 0 | n/a | 1.0 | n/a | correct 14 |
| F ambiguous | 13 | 0 | n/a | 1.0 | n/a | correct 13 |
| G abstention | 11 | 0 | n/a | n/a | n/a | answered_other 11 |

By wording: reserved (n=31): precision 1.0, recall 0.895, false supersession 0.0; seen (n=59): precision 1.0, recall 0.97, false supersession 0.0
Verdicts (gold -> validated): insufficient -> insufficient 12, insufficient -> unrelated 1, supersedes -> contradicts 2, supersedes -> supersedes 49, supersedes -> unrelated 1, unrelated -> insufficient 11, unrelated -> unrelated 14
Failed validator checks: {'target_in_candidates': 1}; decided by: {'classifier': 90}; gold key among candidates: 1.0

**D agent, then classifier**, by category

| category | n | tags | right target | current_acc | stale | outcomes |
|---|---|---|---|---|---|---|
| A explicit | 11 | 11 | 1.0 | 0.727 | 0.0 | correct 8, wrong 3 |
| B direct implicit | 14 | 14 | 1.0 | 0.857 | 0.0 | correct 12, wrong 2 |
| C indirect implicit | 14 | 14 | 1.0 | 0.929 | 0.0 | correct 13, wrong 1 |
| D event-based | 13 | 13 | 1.0 | 0.923 | 0.0 | correct 12, wrong 1 |
| E unrelated but similar | 14 | 0 | n/a | 1.0 | n/a | correct 14 |
| F ambiguous | 13 | 1 | n/a | 0.923 | n/a | correct 12, overridden 1 |
| G abstention | 11 | 0 | n/a | n/a | n/a | answered_other 11 |

By wording: reserved (n=31): precision 1.0, recall 1.0, false supersession 0.0; seen (n=59): precision 0.971, recall 1.0, false supersession 0.038
Verdicts (gold -> validated): insufficient -> insufficient 11, insufficient -> supersedes 1, insufficient -> unrelated 1, supersedes -> supersedes 52, unrelated -> insufficient 11, unrelated -> unrelated 14
Failed validator checks: none; decided by: {'agent': 50, 'classifier': 40}; gold key among candidates: 1.0

Model calls: {"model": "haiku", "real_calls_this_run": 0, "cache_hits": 310, "agent_parse_failures": 0, "classifier_parse_failures": 0, "seconds_per_call_median": null}

## bench/temporal held-out adversarial cases (n=1000), before and after

| arm | stale (of 36) | correct | other | tags on the 36 | right target | tags on 25 noise lines | all held-out current_acc | all held-out stale_rate |
|---|---|---|---|---|---|---|---|---|
| A current plainmem | 36 | 0 | 0 | 0 | 0 | 0 | 0.763 | 0.158 |
| B agent-declared (simulated) | 4 | 31 | 1 | 32 | 32 | 0 | 0.899 | 0.018 |
| C classifier | 4 | 31 | 1 | 32 | 32 | 0 | 0.899 | 0.018 |
| D agent, then classifier | 1 | 34 | 1 | 35 | 35 | 0 | 0.912 | 0.004 |

Model calls: {"real_calls_this_run": 0, "cache_hits": 212}

Model calls over the whole experiment (run 2: dev rounds, held-out, temporal): 1395 (`llm_calls.jsonl`).
