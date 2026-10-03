# Dev rounds (dev split only, 210 cases)

Kept so the tuning history is visible. Held-out was run once, after round 2.

Round 1 (commit 54a3eab prompts):

| arm | precision | recall | false_supersession | abstention_rate | stale_rate | implicit_stale | current_acc | g_abstained | tags_written | wrong_target |
|---|---|---|---|---|---|---|---|---|---|---|
| A current plainmem | n/a | 0.0 | 0.0 | n/a | 1.0 | 1.0 | 0.341 | 0.0 | 0 | 0 |
| B agent-declared (simulated) | 0.922 | 0.967 | 0.102 | 0.0 | 0.033 | 0.041 | 0.854 | 0.0 | 128 | 1 |
| C classifier | 0.982 | 0.877 | 0.023 | 0.205 | 0.123 | 0.155 | 0.827 | 0.0 | 109 | 0 |
| D agent, then classifier | 0.915 | 0.967 | 0.114 | 0.119 | 0.033 | 0.041 | 0.849 | 0.0 | 129 | 1 |

Abstention 2x2 (true supersessions: detected / wrong target / abstained / rejected; unrelated+ambiguous: rejected / abstained / falsely tagged):

| arm | detected | wrong target | abstained | rejected | | rejected | abstained | falsely tagged |
|---|---|---|---|---|---|---|---|---|
| A current plainmem | 0 | 0 | 0 | 122 | | 88 | 0 | 0 |
| B agent-declared (simulated) | 118 | 1 | 0 | 3 | | 79 | 0 | 9 |
| C classifier | 107 | 0 | 12 | 3 | | 55 | 31 | 2 |

Changes after round 1 (commit b804191): the skill rule and the classifier's "insufficient" wording now say that a note about what someone has been doing, might do, or did once is not a replacement; candidates are listed in key order in both prompts. Round 1 false tags were mostly ambiguous notes ("has been running X lately"): agent 9 of 88, classifier 2 of 88.

Round 2:

| arm | precision | recall | false_supersession | abstention_rate | stale_rate | implicit_stale | current_acc | g_abstained | tags_written | wrong_target |
|---|---|---|---|---|---|---|---|---|---|---|
| A current plainmem | n/a | 0.0 | 0.0 | n/a | 1.0 | 1.0 | 0.341 | 0.0 | 0 | 0 |
| B agent-declared (simulated) | 0.991 | 0.902 | 0.0 | 0.0 | 0.098 | 0.113 | 0.854 | 0.0 | 111 | 1 |
| C classifier | 1.0 | 0.869 | 0.0 | 0.281 | 0.131 | 0.165 | 0.832 | 0.0 | 106 | 0 |
| D agent, then classifier | 0.991 | 0.934 | 0.0 | 0.238 | 0.066 | 0.082 | 0.876 | 0.0 | 115 | 1 |

Abstention 2x2 (true supersessions: detected / wrong target / abstained / rejected; unrelated+ambiguous: rejected / abstained / falsely tagged):

| arm | detected | wrong target | abstained | rejected | | rejected | abstained | falsely tagged |
|---|---|---|---|---|---|---|---|---|
| A current plainmem | 0 | 0 | 0 | 122 | | 88 | 0 | 0 |
| B agent-declared (simulated) | 110 | 1 | 0 | 11 | | 88 | 0 | 0 |
| C classifier | 106 | 0 | 13 | 3 | | 42 | 46 | 0 |

A lexical heuristic (change word plus exactly one matching candidate, no model) was tried before round 1: precision 0.704, recall 0.156, no false tags on dev. It was dropped.
