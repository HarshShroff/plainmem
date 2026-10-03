# Run 2 dev rounds (dev split only, 210 cases, seed 4127)

Held-out (90 cases) was run once, after round 2. Every change below was made from dev failures only.

## Round 1: run-1 final configuration, unchanged (commit b39d390)

| arm | precision | recall | false_supersession | abstention_rate | stale_rate | implicit_stale | current_acc | g_abstained | tags_written | wrong_target |
|---|---|---|---|---|---|---|---|---|---|---|
| A current plainmem | n/a | 0.0 | 0.0 | n/a | 1.0 | 1.0 | 0.341 | 0.0 | 0 | 0 |
| B agent-declared (simulated) | 0.964 | 0.877 | 0.023 | 0.0 | 0.123 | 0.155 | 0.849 | 0.0 | 111 | 2 |
| C classifier | 0.99 | 0.852 | 0.0 | 0.281 | 0.148 | 0.186 | 0.838 | 0.0 | 105 | 1 |
| D agent, then classifier | 0.965 | 0.902 | 0.023 | 0.243 | 0.098 | 0.124 | 0.865 | 0.0 | 114 | 2 |

Abstention 2x2 (true supersessions: detected / wrong target / abstained / rejected; unrelated+ambiguous: rejected / abstained / falsely tagged):

| arm | detected | wrong target | abstained | rejected | | rejected | abstained | falsely tagged |
|---|---|---|---|---|---|---|---|---|
| A current plainmem | 0 | 0 | 0 | 122 | | 88 | 0 | 0 |
| B agent-declared (simulated) | 107 | 2 | 0 | 13 | | 86 | 0 | 2 |
| C classifier | 104 | 1 | 9 | 8 | | 38 | 50 | 0 |
| D agent, then classifier | 110 | 2 | 2 | 8 | | 37 | 49 | 2 |

Dev failures that drove the round-2 change:
- Indirect wording missed by both B and C: "X purchases need Y's approval from now on" (budget owner, missed in 6 of 6 for B), "X pages go to Y" (on-call engineer), "X mockups go through Y" / "Y reviews all X mockups now" (design reviewer), "X runs on Y these days" (primary database). The classifier's reasons were mostly "no matching key on file" or "does not explicitly say it changed".
- Wrong sibling: "FjordStack pipelines live on CircleCI now" filed as CD provider (B and C); "KestrelStack pages go to Y" filed as Design reviewer (B).
- False tags (B only): "EmberPoint added a read replica in sa-east-1" -> Backup region; "Noor Orsolo might take over SaffronPoint" -> Project lead.
- Many vendor questions answered from the "backup vendor" line although the right key was tagged (read path, see README; not a write-path error and not part of the bar).

## Changes after round 1 (commit after this file)

- Classifier prompt (`src/plainmem/consolidate_llm.py`), new "Matching a key" block: (1) a note may name a fact by what its holder does (paged, approves purchases, reviews designs, where it runs, what builds run on, who it buys from), map it to that key; (2) a note saying outright who or what holds the role now ("from now on", "these days") with a different value supersedes even without the old value; (3) a key with a qualifier the note does not use (backup, replica, staging, secondary) is not the target.
- Skill rule (`skills/plainmem-memory/SKILL.md`, what arm B sees): the same three points in one sentence each.
- No validator or candidate-retrieval change (gold key was among the candidates for 100% of dev updates).
- Tried and reverted (not part of the frozen configuration): an `explain` tie-break preferring keys with fewer extra words. It fixed the vendor/backup-vendor read on dev but lowered plainmem+hybrid current_acc on `bench/temporal`; see README.

These hints were written with knowledge of the benchmark's attribute list, which is the main overfitting risk. The reserved held-out wordings and the 36 temporal cases are the partial check.

## Round 2 (frozen configuration)

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

Remaining dev failures: B still made 3 false tags (read replica -> Backup region again, "has been running X lately" -> Project lead, "may sign with Y" -> Vendor) and missed 8 indirect updates; C missed "purchases need Y's approval" once and filed "pipelines live on CircleCI" as CD provider again. Not tuned further: the call budget left room for held-out and the temporal rerun only.

Model calls after round 2: 1,057 (round 1: 525, round 2: 532).
