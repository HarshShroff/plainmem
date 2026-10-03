## bench/temporal held-out adversarial cases (n=1000), before and after

| arm | stale (of 36) | correct | other | tags on the 36 | right target | tags on 25 noise lines | all held-out current_acc | all held-out stale_rate |
|---|---|---|---|---|---|---|---|---|
| A current plainmem | 36 | 0 | 0 | 0 | 0 | 0 | 0.763 | 0.158 |
| B agent-declared (simulated) | 4 | 31 | 1 | 32 | 32 | 0 | 0.899 | 0.018 |
| C classifier | 4 | 31 | 1 | 32 | 32 | 0 | 0.899 | 0.018 |
| D agent, then classifier | 1 | 34 | 1 | 35 | 35 | 0 | 0.912 | 0.004 |

Model calls: {"real_calls_this_run": 0, "cache_hits": 212}
