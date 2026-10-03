# Temporal benchmark

The claim under test: explicit temporal and provenance semantics cut stale answers more than better retrieval does. The benchmark is designed so it could say no. If plainmem's stale-answer rate came out close to BM25's, or if the gain tracked retrieval recall rather than the lifecycle logic, the claim would be wrong.

## Reproduce

```bash
python bench/temporal/generate.py --cases 1000 --seed 2026 --out /tmp/temporal   # inspect the data
python bench/temporal/run.py                    # all sizes, both splits; writes results.md and results.json
python bench/temporal/run.py --split dev --show-failures 1 --no-write   # what tuning is allowed to look at
```

`split.json` records the seed, the held-out ids for each size and the SHA-256 of each generated `cases.jsonl`, so a regenerated set can be checked against the frozen one.

## Data

One shared corpus per size (100, 500 and 1,000 cases). Each case owns one entity and attribute, so cases never collide, but they share files, log days and vocabulary. Entity files (`projects/<name>.md`) hold the base values under a front matter `updated:` date in late 2025. Changes go into `logs/2026-Q1..Q3.md` under dated headings. Every file's mtime is set to the same day, so mtime never decides anything. Noise bullets and untagged background facts make up the rest.

| category | share | what it tests |
|---|---|---|
| single_update | 12% | base value, one later update |
| multi_update | 12% | two to four sequential updates |
| contradictory | 8% | two values on the same day, one `{explicit, user}`, one `{inferred, agent}`; the explicit one is right |
| distractor | 10% | look-alike facts sharing words with the key (sibling keys, another entity's same key) |
| stable | 8% | never changes |
| now_query | 8% | several updates, asked "right now" / "currently" |
| as_of | 14% | "what was X on date T", T strictly between two changes; a third have a back-dated `{explicit, user, from D}` update with T between D and the log date |
| provenance | 10% | "where did X come from"; right citation, plus the source word when the line is tagged |
| adversarial | 12% | update worded with no shared key words ("Priya took over from Sam on Orion") |
| paraphrase | 6% | question shares no content word with the attribute ("Which datacenter location hosts X?") |

The held-out split is 30% of each category, chosen with `random.Random(seed + 1)`. It was frozen and committed before any system was run on the data.

## Systems and metrics

- `bm25-raw` and `bm25`: BM25 without and with stemming. The answer is the top chunk's text.
- `plainmem-search`: plainmem's full ranker (decay, superseded chunks demoted, the superseding chunk lifted). The answer is the top chunk. Same index as below.
- `plainmem`: `explain`, which picks a fact and resolves it through the supersession chain, the tags and `as_of`. The answer is the reported value, citation and source.
- `plainmem+hybrid`: `explain` with BM25 + all-MiniLM-L6-v2 candidates fused by RRF. Needs `pip install -e ".[embeddings]"`; included in the committed run.

A chunk-text answer counts as correct if it contains the expected value. That is generous to the baselines, since a chunk that mentions both the old and the new value counts as right. "Stale" means a current-state question was answered with a superseded value and not the right one. Recall@k asks whether the line that states the right value is in the top k search results (plainmem's search is as-of-aware for as-of questions). Latency is the time to answer one question with the index already built.

## Process

1. Generator written and split frozen (commit "temporal benchmark generator and frozen held-out split").
2. First dev run. Two dev-only failure modes were fixed. `explain` used to follow the first hit whose key shared any word with the question, which often meant only the entity name; it now takes the key with the most shared words. And the as-of date in the question was being matched as words against unrelated dates and IDs; it is now treated as a filter. On dev at n=1,000 the two fixes together moved as-of accuracy from 0.592 to 1.000, recall@5 from 0.840 to 0.870, provenance accuracy from 0.986 to 1.000 and current-state accuracy from 0.759 to 0.765.
3. Held-out run, once. Afterwards, three changes were made that do not touch answer selection: answer timing no longer counts the separate recall search, the fact table is cached per index, and `explain --as-of` before any record says "none" instead of "no match". The benchmark was re-run after each of them and every accuracy figure was identical; only the latency columns changed.

## Results (held-out)

| n | system | recall@5 | current acc | stale rate | as-of acc | provenance acc |
|---|---|---|---|---|---|---|
| 100 | bm25 | 0.800 | 0.087 | 0.913 | 0.750 | 0.000 |
| 100 | plainmem | 0.767 | 0.739 | 0.174 | 0.750 | 1.000 |
| 500 | bm25 | 0.867 | 0.105 | 0.842 | 0.333 | 0.000 |
| 500 | plainmem | 0.900 | 0.754 | 0.158 | 1.000 | 1.000 |
| 1000 | bm25 | 0.853 | 0.105 | 0.825 | 0.310 | 0.000 |
| 1000 | plainmem | 0.900 | 0.763 | 0.158 | 1.000 | 1.000 |

At n=100 the held-out set is 30 questions, of which 4 are as-of questions, so that row is noisy. The full tables, per-category breakdowns and failure examples are in `results.md`.

## Reading it

The stale-answer rate fell from 0.825 (BM25) to 0.158 (plainmem) at n=1,000. Stemming, the one retrieval improvement measured here, changed recall@5 by 0.006 and the stale rate by nothing. Recall@5 for BM25 and plainmem is about the same (0.853 against 0.900), so the gap in stale answers isn't coming from finding more of the right lines. It comes from knowing which of the lines found is current. On this data the claim holds against lexical retrieval.

It was also run against semantic retrieval. `plainmem+hybrid` (BM25 plus all-MiniLM-L6-v2 fused by reciprocal rank) leaves the stale rate at 0.158, the same as lexical plainmem, so adding embeddings did not remove stale answers. What it did change: paraphrased questions went from 0 of 18 to 14 of 18 correct (recall@5 0.667 to 1.000), which lifted overall current-state accuracy from 0.763 to 0.820. What it cost: as-of accuracy fell from 1.000 to 0.929 (as-of recall@5 1.000 to 0.786, the embedding candidates pushed out the dated lines), and the median answer takes about 94 ms instead of 7 ms. Adversarial updates are untouched: still 36 of 36 stale, because an update that shares no key words with its fact is not linked by embeddings either. The hybrid row uses one embedding model, one fusion constant and no tuning beyond dev, so treat it as one data point, not a verdict on embeddings.

The search-only row shows where the gain sits. Ranking with supersession (`plainmem-search`) already brings the stale rate down to 0.158, the same as `explain`. But for as-of questions, ranking for the present is worse than plain BM25 (0.095 against 0.310). Only the explicit as-of path gets them right (1.000).

Some categories favour plainmem by construction. Contradictory questions are only solvable through the authority tag, provenance questions reward returning a citation, and back-dated as-of questions need the `from` tag. BM25 scores 0.000 on provenance because its top hit is almost always the old base line in the entity file, not the update.

## Failures (held-out, plainmem)

| n | category | outcome | count |
|---|---|---|---|
| 1000 | adversarial | stale, update not retrieved in top 5 | 24 |
| 1000 | adversarial | stale, update retrieved but not linked | 12 |
| 1000 | paraphrase | wrong fact picked | 12 |
| 1000 | paraphrase | wrong, not retrieved | 6 |
| 500 | adversarial | stale (10 not retrieved, 8 retrieved) | 18 |
| 500 | paraphrase | wrong (5 not retrieved, 4 retrieved) | 9 |
| 500 | distractor | wrong fact picked | 1 |
| 100 | adversarial | stale, not retrieved | 4 |
| 100 | paraphrase | wrong, not retrieved | 2 |
| 100 | as_of | wrong, not retrieved | 1 |

- Adversarial updates are the main open failure, and they are a lifecycle failure as much as a retrieval one. Even when the update line was retrieved (12 of 36 at n=1,000), plainmem can't tell it replaces the old value, because supersession works by key and the line has no key. Better retrieval would not fix those 12. Writing `{supersedes Orion project lead}` on the line fixes it (tested), but nothing infers it.
- Paraphrased questions fail because `explain` picks facts by shared key words. When only the entity name matches, it returns another fact about the same entity. Example: "Which datacenter location hosts PinnacleDeck?" returned the cache layer, `Varnish`.
- n=500 distractor: "What is the HarborFold vendor?" returned `bronze`, the value of a sibling key ("vendor tier"). It ties with the right key on shared words and was ranked higher.
- n=100 as-of: "What was the MeridianPoint CI provider on 2026-07-22?" returned another project's CI provider. The right line was not in the top results.

## Step-4 rule

Agreed before the run: if recall@5 on the temporal set is below about 0.9, build hybrid retrieval as an optional path; if it is at or above 0.9 but stale answers remain, fix lifecycle reasoning instead. On dev at n=1,000, plainmem's recall@5 was 0.870, so hybrid was built (`src/plainmem/hybrid.py`, `--mode hybrid`, `plainmem[embeddings]`). Held-out recall@5 then came out at exactly 0.900, right on the line. The hybrid path is unit tested with a stub embedder but has not been benchmarked, for the reason above. The stale answers that remain are adversarial updates, and hybrid retrieval can at best surface those lines. It can't link them to a key, so lifecycle work is still needed whatever the hybrid numbers turn out to be.
