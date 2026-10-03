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

