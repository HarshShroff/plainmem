import re
import sys
import time
from datetime import date
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "bench"
sys.path.insert(0, str(BENCH))

from temporal import generate as tg  # noqa: E402

TOL = 2


@pytest.fixture(scope="module")
def b100():
    return tg.generate(100, 2026)


def _snapshot(b):
    return b.files, [tg.asdict(c) for c in b.cases], b.mtimes


def test_deterministic() -> None:
    a, b = tg.generate(100, 5), tg.generate(100, 5)
    assert _snapshot(a) == _snapshot(b)
    assert _snapshot(tg.generate(100, 6)) != _snapshot(a)


@pytest.mark.parametrize("n", [100, 500, 1000])
def test_sizes_and_mix(n: int) -> None:
    b = tg.generate(n, 11)
    assert len(b.cases) == n
    assert len({c.id for c in b.cases}) == n
    for cat, pct in tg.MIX.items():
        got = sum(c.category == cat for c in b.cases)
        assert abs(got - n * pct / 100) <= TOL, (cat, got)
        cs = [c for c in b.cases if c.category == cat]
        held = sum(c.split == "heldout" for c in cs)
        assert abs(held - tg.HELDOUT_FRACTION * len(cs)) <= 1, (cat, held, len(cs))
    assert len({c.entity for c in b.cases}) == n


def test_mtimes_all_now(b100) -> None:
    assert set(b100.mtimes) == set(b100.files)
    assert len(set(b100.mtimes.values())) == 1


def test_cites_point_at_expected_value(b100) -> None:
    for c in b100.cases:
        path, ln = c.expected_cite.rsplit(":", 1)
        line = b100.files[path].split("\n")[int(ln) - 1]
        assert c.expected in line, (c.id, line)
        if path.startswith("logs/"):
            assert c.entity in line, (c.id, line)
        for s in c.stale_values:
            if s != c.expected and s not in c.expected:
                assert s not in line or c.category == "adversarial", (c.id, line)
        if c.expected_source:
            assert f", {c.expected_source}" in line and line.rstrip().endswith("}")


def test_as_of_windows(b100) -> None:
    n_back = n_asof = 0
    for c in b100.cases:
        if c.category != "as_of":
            assert c.as_of is None
            continue
        n_asof += 1
        a = date.fromisoformat(c.as_of)
        eff = [(date.fromisoformat(d), v) for d, v in c.timeline]
        assert eff == sorted(eff)
        assert all(a != d for d, _ in eff)
        before = [(d, v) for d, v in eff if d < a]
        after = [d for d, _ in eff if d > a]
        assert before and (after or c.backdated), c.id
        assert before[-1][1] == c.expected
        assert c.expected not in c.stale_values
        path, ln = c.expected_cite.rsplit(":", 1)
        line = b100.files[path].split("\n")[int(ln) - 1]
        m = re.search(r"from (\d{4}-\d\d-\d\d)", line)
        if c.backdated:
            n_back += 1
            assert m, line
            frm = date.fromisoformat(m.group(1))
            head = _heading_for(b100.files[path], int(ln))
            assert frm < a < head
        assert not (m and not c.backdated)
    assert n_asof and 0 < n_back < n_asof


def _heading_for(text: str, ln: int) -> date:
    for line in reversed(text.split("\n")[:ln]):
        if line.startswith("## "):
            return date.fromisoformat(line[3:].strip())
    raise AssertionError("no heading")


def test_dates_ranges(b100) -> None:
    for path, text in b100.files.items():
        if path.startswith("logs/"):
            heads = [date.fromisoformat(x[3:]) for x in text.split("\n") if x.startswith("## ")]
            assert heads == sorted(heads)
            assert all(date(2026, 1, 5) <= h <= date(2026, 9, 25) for h in heads)
        else:
            m = re.search(r"updated: (\S+)", text)
            assert date(2025, 10, 1) <= date.fromisoformat(m.group(1)) <= date(2025, 12, 31)


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in {"on", "of", "the", "a", "an", "is"}}


def test_adversarial_and_paraphrase_share_no_key_words(b100) -> None:
    seen = set()
    for c in b100.cases:
        attr_words = _words(c.attribute)
        if c.category == "adversarial":
            path, ln = c.expected_cite.rsplit(":", 1)
            line = b100.files[path].split("\n")[int(ln) - 1]
            assert c.entity in line
            assert not (_words(line.replace(c.entity, "")) & attr_words), (c.id, line)
            seen.add(c.id)
        if c.category == "paraphrase":
            assert not (_words(c.question.replace(c.entity, "")) & attr_words), c.question
    assert seen


def test_contradictory_and_provenance(b100) -> None:
    for c in b100.cases:
        if c.category == "contradictory":
            path, ln = c.expected_cite.rsplit(":", 1)
            lines = b100.files[path].split("\n")
            assert "{explicit, user}" in lines[int(ln) - 1]
            assert any("{inferred, agent}" in x and c.stale_values[0] in x for x in lines)
            assert c.expected_source == "user"
        if c.category == "provenance":
            assert c.query_type == "provenance" and c.expected_source


def test_large_corpus_is_fast() -> None:
    t = time.perf_counter()
    tg.generate(1000, 3)
    assert time.perf_counter() - t < 5


def test_write(tmp_path, b100) -> None:
    import json

    tg.write(b100, tmp_path, 2026)
    assert (tmp_path / "notes" / "logs" / "2026-Q1.md").exists()
    rows = [json.loads(x) for x in (tmp_path / "cases.jsonl").read_text().splitlines()]
    assert len(rows) == 100
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert man["n_cases"] == 100 and man["split_seed_offset"] == 1 and len(man["cases_sha256"]) == 64
