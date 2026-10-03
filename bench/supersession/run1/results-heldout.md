## Split: heldout (90 cases)

| arm | precision | recall | false_supersession | abstention_rate | stale_rate | implicit_stale | current_acc | g_abstained | tags_written | wrong_target |
|---|---|---|---|---|---|---|---|---|---|---|
| A current plainmem | n/a | 0.0 | 0.0 | n/a | 1.0 | 1.0 | 0.342 | 0.0 | 0 | 0 |
| B agent-declared (simulated) | 0.935 | 0.827 | 0.026 | 0.0 | 0.173 | 0.22 | 0.848 | 0.0 | 46 | 2 |
| C classifier | 0.976 | 0.788 | 0.026 | 0.3 | 0.212 | 0.268 | 0.823 | 0.0 | 42 | 0 |
| D agent, then classifier | 0.938 | 0.865 | 0.026 | 0.256 | 0.135 | 0.171 | 0.873 | 0.0 | 48 | 2 |

Abstention 2x2 (true supersessions: detected / wrong target / abstained / rejected; unrelated+ambiguous: rejected / abstained / falsely tagged):

| arm | detected | wrong target | abstained | rejected | | rejected | abstained | falsely tagged |
|---|---|---|---|---|---|---|---|---|
| A current plainmem | 0 | 0 | 0 | 52 | | 38 | 0 | 0 |
| B agent-declared (simulated) | 43 | 2 | 0 | 7 | | 37 | 0 | 1 |
| C classifier | 41 | 0 | 7 | 4 | | 17 | 20 | 1 |
| D agent, then classifier | 45 | 2 | 3 | 2 | | 17 | 20 | 1 |

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
| A explicit | 11 | 11 | 1.0 | 1.0 | 0.0 | correct 11 |
| B direct implicit | 14 | 14 | 1.0 | 1.0 | 0.0 | correct 14 |
| C indirect implicit | 14 | 8 | 0.429 | 0.286 | 0.571 | correct 4, stale 8, wrong 2 |
| D event-based | 13 | 12 | 0.923 | 0.846 | 0.077 | correct 11, stale 1, wrong 1 |
| E unrelated but similar | 14 | 1 | n/a | 1.0 | n/a | correct 14 |
| F ambiguous | 13 | 0 | n/a | 1.0 | n/a | correct 13 |
| G abstention | 11 | 0 | n/a | n/a | n/a | answered_other 11 |

By wording: reserved (n=31): precision 0.85, recall 0.895, false supersession 0.083; seen (n=59): precision 1.0, recall 0.788, false supersession 0.0
Verdicts (gold -> validated): insufficient -> unrelated 13, supersedes -> supersedes 45, supersedes -> unrelated 7, unrelated -> supersedes 1, unrelated -> unrelated 24
Failed validator checks: none; decided by: {'agent': 90}; gold key among candidates: 1.0

**C classifier**, by category

| category | n | tags | right target | current_acc | stale | outcomes |
|---|---|---|---|---|---|---|
| A explicit | 11 | 11 | 1.0 | 1.0 | 0.0 | correct 11 |
| B direct implicit | 14 | 14 | 1.0 | 1.0 | 0.0 | correct 14 |
| C indirect implicit | 14 | 6 | 0.429 | 0.286 | 0.571 | correct 4, stale 8, wrong 2 |
| D event-based | 13 | 10 | 0.769 | 0.692 | 0.231 | correct 9, stale 3, wrong 1 |
| E unrelated but similar | 14 | 1 | n/a | 1.0 | n/a | correct 14 |
| F ambiguous | 13 | 0 | n/a | 1.0 | n/a | correct 13 |
| G abstention | 11 | 0 | n/a | n/a | n/a | answered_other 11 |

By wording: reserved (n=31): precision 0.938, recall 0.789, false supersession 0.083; seen (n=59): precision 1.0, recall 0.788, false supersession 0.0
Verdicts (gold -> validated): insufficient -> insufficient 12, insufficient -> unrelated 1, supersedes -> contradicts 2, supersedes -> insufficient 7, supersedes -> supersedes 41, supersedes -> unrelated 2, unrelated -> insufficient 8, unrelated -> supersedes 1, unrelated -> unrelated 16
Failed validator checks: none; decided by: {'classifier': 90}; gold key among candidates: 1.0

**D agent, then classifier**, by category

| category | n | tags | right target | current_acc | stale | outcomes |
|---|---|---|---|---|---|---|
| A explicit | 11 | 11 | 1.0 | 1.0 | 0.0 | correct 11 |
| B direct implicit | 14 | 14 | 1.0 | 1.0 | 0.0 | correct 14 |
| C indirect implicit | 14 | 10 | 0.571 | 0.429 | 0.429 | correct 6, stale 6, wrong 2 |
| D event-based | 13 | 12 | 0.923 | 0.846 | 0.077 | correct 11, stale 1, wrong 1 |
| E unrelated but similar | 14 | 1 | n/a | 1.0 | n/a | correct 14 |
| F ambiguous | 13 | 0 | n/a | 1.0 | n/a | correct 13 |
| G abstention | 11 | 0 | n/a | n/a | n/a | answered_other 11 |

By wording: reserved (n=31): precision 0.85, recall 0.895, false supersession 0.083; seen (n=59): precision 1.0, recall 0.848, false supersession 0.0
Verdicts (gold -> validated): insufficient -> insufficient 12, insufficient -> unrelated 1, supersedes -> insufficient 3, supersedes -> supersedes 47, supersedes -> unrelated 2, unrelated -> insufficient 8, unrelated -> supersedes 1, unrelated -> unrelated 16
Failed validator checks: none; decided by: {'agent': 46, 'classifier': 44}; gold key among candidates: 1.0

Model calls: {"model": "haiku", "real_calls_this_run": 193, "cache_hits": 301, "agent_parse_failures": 0, "classifier_parse_failures": 0, "seconds_per_call_median": 6.22}

