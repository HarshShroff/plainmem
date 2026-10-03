## bench/temporal held-out adversarial cases (n=1000), before and after

| arm | stale (of 36) | correct | other | tags on the 36 | right target | tags on 25 noise lines | all held-out current_acc | all held-out stale_rate |
|---|---|---|---|---|---|---|---|---|
| A current plainmem | 36 | 0 | 0 | 0 | 0 | 0 | 0.763 | 0.158 |
| B agent-declared (simulated) | 5 | 30 | 1 | 31 | 31 | 0 | 0.895 | 0.022 |
| C classifier | 12 | 24 | 0 | 24 | 24 | 0 | 0.868 | 0.053 |
| D agent, then classifier | 3 | 32 | 1 | 33 | 33 | 0 | 0.904 | 0.013 |

Model calls: {"real_calls_this_run": 122, "cache_hits": 213}
