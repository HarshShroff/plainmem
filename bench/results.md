Corpus: 426 files, 2721 chunks, 158 queries {'lookup': 40, 'paraphrase': 42, 'stale': 40, 'superseded': 36}, reference date 2026-09-29, seed 7.

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

plainmem index: build 0.093s, load 0.039s, 712 KiB on disk; 36 conflicting keys detected.
Embedding baseline (all-MiniLM-L6-v2): encode 2.0s on CPU, 4082 KiB of vectors in memory.
