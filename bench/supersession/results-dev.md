## Split: dev (210 cases)

| arm | precision | recall | false_supersession | abstention_rate | stale_rate | implicit_stale | current_acc | g_abstained | tags_written | wrong_target |
|---|---|---|---|---|---|---|---|---|---|---|
| A current plainmem | n/a | 0.0 | 0.0 | n/a | 1.0 | 1.0 | 0.341 | 0.0 | 0 | 0 |
| B agent-declared (simulated) | 0.974 | 0.934 | 0.034 | 0.0 | 0.066 | 0.082 | 0.881 | 0.0 | 117 | 0 |
| C classifier | 0.992 | 0.984 | 0.0 | 0.267 | 0.016 | 0.021 | 0.924 | 0.0 | 121 | 1 |
| D agent, then classifier | 0.968 | 0.992 | 0.034 | 0.257 | 0.008 | 0.01 | 0.919 | 0.0 | 125 | 1 |

Abstention 2x2 (true supersessions: detected / wrong target / abstained / rejected; unrelated+ambiguous: rejected / abstained / falsely tagged):

| arm | detected | wrong target | abstained | rejected | | rejected | abstained | falsely tagged |
|---|---|---|---|---|---|---|---|---|
| A current plainmem | 0 | 0 | 0 | 122 | | 88 | 0 | 0 |
| B agent-declared (simulated) | 114 | 0 | 0 | 8 | | 85 | 0 | 3 |
| C classifier | 120 | 1 | 0 | 1 | | 32 | 56 | 0 |
| D agent, then classifier | 121 | 1 | 0 | 0 | | 31 | 54 | 3 |

**A current plainmem**, by category

| category | n | tags | right target | current_acc | stale | outcomes |
|---|---|---|---|---|---|---|
| A explicit | 25 | 0 | 0.0 | 0.0 | 1.0 | stale 25 |
| B direct implicit | 34 | 0 | 0.0 | 0.0 | 1.0 | stale 34 |
| C indirect implicit | 34 | 0 | 0.0 | 0.0 | 1.0 | stale 34 |
| D event-based | 29 | 0 | 0.0 | 0.0 | 1.0 | stale 29 |
| E unrelated but similar | 34 | 0 | n/a | 1.0 | n/a | correct 34 |
| F ambiguous | 29 | 0 | n/a | 1.0 | n/a | correct 29 |
| G abstention | 25 | 0 | n/a | n/a | n/a | answered_other 25 |

**B agent-declared (simulated)**, by category

| category | n | tags | right target | current_acc | stale | outcomes |
|---|---|---|---|---|---|---|
| A explicit | 25 | 25 | 1.0 | 0.96 | 0.0 | correct 24, wrong 1 |
| B direct implicit | 34 | 33 | 0.971 | 0.912 | 0.029 | correct 31, stale 1, wrong 2 |
| C indirect implicit | 34 | 27 | 0.794 | 0.618 | 0.206 | correct 21, stale 7, wrong 6 |
| D event-based | 29 | 29 | 1.0 | 0.897 | 0.0 | correct 26, wrong 3 |
| E unrelated but similar | 34 | 1 | n/a | 1.0 | n/a | correct 34 |
| F ambiguous | 29 | 2 | n/a | 0.931 | n/a | correct 27, overridden 1, wrong 1 |
| G abstention | 25 | 0 | n/a | n/a | n/a | answered_other 25 |

Verdicts (gold -> validated): insufficient -> supersedes 2, insufficient -> unrelated 27, supersedes -> supersedes 114, supersedes -> unrelated 8, unrelated -> supersedes 1, unrelated -> unrelated 58
Failed validator checks: none; decided by: {'agent': 210}; gold key among candidates: 1.0

**C classifier**, by category

| category | n | tags | right target | current_acc | stale | outcomes |
|---|---|---|---|---|---|---|
| A explicit | 25 | 25 | 1.0 | 0.96 | 0.0 | correct 24, wrong 1 |
| B direct implicit | 34 | 34 | 1.0 | 0.941 | 0.0 | correct 32, wrong 2 |
| C indirect implicit | 34 | 33 | 0.941 | 0.765 | 0.059 | correct 26, stale 2, wrong 6 |
| D event-based | 29 | 29 | 1.0 | 0.897 | 0.0 | correct 26, wrong 3 |
| E unrelated but similar | 34 | 0 | n/a | 1.0 | n/a | correct 34 |
| F ambiguous | 29 | 0 | n/a | 1.0 | n/a | correct 29 |
| G abstention | 25 | 0 | n/a | n/a | n/a | answered_other 25 |

Verdicts (gold -> validated): insufficient -> insufficient 28, insufficient -> unrelated 1, supersedes -> supersedes 121, supersedes -> unrelated 1, unrelated -> insufficient 28, unrelated -> unrelated 31
Failed validator checks: none; decided by: {'classifier': 210}; gold key among candidates: 1.0

**D agent, then classifier**, by category

| category | n | tags | right target | current_acc | stale | outcomes |
|---|---|---|---|---|---|---|
| A explicit | 25 | 25 | 1.0 | 0.96 | 0.0 | correct 24, wrong 1 |
| B direct implicit | 34 | 34 | 1.0 | 0.941 | 0.0 | correct 32, wrong 2 |
| C indirect implicit | 34 | 34 | 0.971 | 0.794 | 0.029 | correct 27, stale 1, wrong 6 |
| D event-based | 29 | 29 | 1.0 | 0.897 | 0.0 | correct 26, wrong 3 |
| E unrelated but similar | 34 | 1 | n/a | 1.0 | n/a | correct 34 |
| F ambiguous | 29 | 2 | n/a | 0.931 | n/a | correct 27, overridden 1, wrong 1 |
| G abstention | 25 | 0 | n/a | n/a | n/a | answered_other 25 |

Verdicts (gold -> validated): insufficient -> insufficient 26, insufficient -> supersedes 2, insufficient -> unrelated 1, supersedes -> supersedes 122, unrelated -> insufficient 28, unrelated -> supersedes 1, unrelated -> unrelated 30
Failed validator checks: none; decided by: {'agent': 117, 'classifier': 93}; gold key among candidates: 1.0

Model calls: {"model": "haiku", "real_calls_this_run": 0, "cache_hits": 723, "agent_parse_failures": 0, "classifier_parse_failures": 0, "seconds_per_call_median": null}

