from datetime import date

import pytest

from plainmem import BM25, Engine, RankConfig, engine_from_texts
from plainmem.engine import SUPERSEDED
from plainmem.markdown import parse
from plainmem.text import tokenize

from .conftest import NOW

ORION = "---\nverified: 2025-11-02\n---\n# Orion\n\n## People\n\n- Project lead: Dana Whit\n"
LOG = "# 2026-08-14\n\n- Orion project lead: Sam Okafor.\n"


def test_bm25_prefers_rare_terms_and_handles_empty() -> None:
    bm = BM25([["common", "rare"], ["common"], ["common"]])
    s = bm.scores(["common", "rare"])
    assert s[0] > s[1] == s[2]
    assert bm.idf("rare") > bm.idf("common") > 0
    assert BM25([]).scores(["x"]) == {}
    assert BM25([[]]).scores(["x"]) == {}


def test_bm25_length_normalisation() -> None:
    bm = BM25([["cat"], ["cat"] + ["filler"] * 50])
    s = bm.scores(["cat"])
    assert s[0] > s[1]


def test_stemming_finds_inflected_forms() -> None:
    eng = engine_from_texts({"a.md": "We are relocating the office.\n", "b.md": "Unrelated.\n"})
    assert eng.search("relocate", now=NOW)[0].chunk.path == "a.md"
    raw = engine_from_texts({"a.md": "We are relocating the office.\n"}, stem=False)
    assert raw.search("relocate", now=NOW) == []


def test_heading_path_is_searchable() -> None:
    eng = engine_from_texts({"a.md": "# Orion\n\n## People\n\n- Designer: Lee Park\n"})
    assert eng.search("orion designer", now=NOW)[0].chunk.start_line == 5


def test_no_match_and_empty_corpus() -> None:
    assert engine_from_texts({"a.md": "hello\n"}).search("zzz", now=NOW) == []
    assert engine_from_texts({}).search("anything", now=NOW) == []
    assert engine_from_texts({"a.md": "hello\n"}).search("the of and", now=NOW) == []


def test_invalid_mode_raises() -> None:
    with pytest.raises(ValueError):
        engine_from_texts({"a.md": "x\n"}).search("x", mode="magic")


def test_supersession_puts_newer_fact_first_and_marks_old() -> None:
    eng = engine_from_texts({"projects/orion.md": ORION, "journal/2026-08-14.md": LOG})
    hits = eng.search("who is the orion project lead", now=NOW)
    assert hits[0].chunk.path == "journal/2026-08-14.md"
    assert hits[1].status == SUPERSEDED
    assert hits[1].superseded_by[0].path == "journal/2026-08-14.md"
    assert hits[0].supersedes[0].path == "projects/orion.md"


def test_plain_bm25_mode_has_no_freshness() -> None:
    eng = engine_from_texts({"projects/orion.md": ORION, "journal/2026-08-14.md": LOG})
    hits = eng.search("orion project lead", now=NOW, mode="bm25")
    assert all(h.freshness is None and h.status == "UNKNOWN" and not h.superseded_by for h in hits)


def test_conflict_with_same_date_is_unresolved_and_not_superseded() -> None:
    eng = engine_from_texts(
        {"a.md": "# 2026-01-05\n\n- Wifi password: alpha\n", "b.md": "# 2026-01-05\n\n- Wifi password: beta\n"}
    )
    [c] = eng.conflicts
    assert not c.resolved
    assert not eng.superseded_by


def test_same_value_twice_is_not_a_conflict() -> None:
    eng = engine_from_texts(
        {"a.md": "# 2026-01-05\n\n- Wifi password: alpha\n", "b.md": "# 2026-02-05\n\n- Wifi password: Alpha.\n"}
    )
    assert eng.conflicts == []


def test_three_versions_newest_wins() -> None:
    eng = engine_from_texts(
        {
            "a.md": "# 2026-01-01\n\n- Wifi password: one\n",
            "b.md": "# 2026-02-01\n\n- Wifi password: two\n",
            "c.md": "# 2026-03-01\n\n- Wifi password: three\n",
        }
    )
    [c] = eng.conflicts
    assert eng.chunks[c.winner].path == "c.md" and len(c.losers) == 2


def test_promotion_only_when_query_is_on_topic() -> None:
    texts = {
        "projects/orion.md": ORION + "\nDana wrote the onboarding guide.\n",
        "journal/2026-08-14.md": LOG,
    }
    eng = engine_from_texts(texts)
    hits = eng.search("onboarding guide", now=NOW)
    assert all(h.chunk.path != "journal/2026-08-14.md" for h in hits)


def test_promotion_can_be_disabled() -> None:
    eng = engine_from_texts(
        {"projects/orion.md": ORION, "journal/2026-08-14.md": LOG},
        rank=RankConfig(promote_superseding=False, superseded_penalty=1.0, freshness_weight=0.0),
    )
    hits = eng.search("orion project lead", now=NOW)
    assert {h.chunk.path for h in hits} == {"projects/orion.md", "journal/2026-08-14.md"}


def test_freshness_breaks_ties_toward_newer() -> None:
    eng = engine_from_texts(
        {"a.md": "Kayak rental notes [verified: 2024-01-01]\n", "b.md": "Kayak rental notes [verified: 2026-09-01]\n"}
    )
    assert eng.search("kayak rental", now=NOW)[0].chunk.path == "b.md"
    assert eng.search("kayak rental", now=NOW, mode="bm25")[0].chunk.path == "a.md"


def test_stale_lists_volatile_past_window_oldest_first() -> None:
    eng = engine_from_texts(
        {
            "a.md": "- Pass costs $5 [verified: 2026-01-01]\n- Pass costs $6 [verified: 2025-01-01]\n"
            "- Fresh costs $1 [verified: 2026-09-28]\n- Not volatile [verified: 2020-01-01]\n"
        }
    )
    stale = eng.stale(NOW)
    assert [h.chunk.start_line for h in stale] == [2, 1]
    assert all(h.must_reverify for h in stale)


def test_rerank_accepts_external_scores() -> None:
    eng = engine_from_texts({"projects/orion.md": ORION, "journal/2026-08-14.md": LOG})
    old = next(i for i, c in enumerate(eng.chunks) if c.path == "projects/orion.md")
    new = 1 - old
    hits = eng.rerank({old: 0.9, new: 0.5}, set(tokenize("orion lead")), 5, NOW)
    assert hits[0].chunk.path == "journal/2026-08-14.md"


def test_precomputed_tokens_are_used_when_lengths_match() -> None:
    doc = parse("a.md", "alpha\n\nbeta\n")
    eng = Engine([doc], tokens=[["zzz"], ["beta"]])
    assert eng.search("zzz", now=date(2026, 1, 1))[0].chunk.text == "alpha"
    eng2 = Engine([doc], tokens=[["zzz"]])  # wrong length: recomputed
    assert eng2.search("zzz", now=date(2026, 1, 1)) == []


def test_results_are_deterministic() -> None:
    texts = {f"n{i}.md": "same words here\n" for i in range(20)}
    eng = engine_from_texts(texts)
    a = [h.chunk.path for h in eng.search("same words", k=10, now=NOW)]
    b = [h.chunk.path for h in eng.search("same words", k=10, now=NOW)]
    assert a == b == sorted(a)
