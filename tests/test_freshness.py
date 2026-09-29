from datetime import date, datetime, timedelta, timezone

import pytest

from plainmem.freshness import AGING, FRESH, STALE, FreshnessConfig, assess, effective_date, mtime_to_date
from plainmem.markdown import parse

from .conftest import NOW, epoch

CFG = FreshnessConfig()


def one(text: str, mtime: float = 0.0):
    doc = parse("a.md", text, mtime)
    return doc.chunks[0], doc


@pytest.mark.parametrize(
    ("age", "status"),
    [(0, FRESH), (90, FRESH), (91, AGING), (365, AGING), (366, STALE), (2000, STALE)],
)
def test_status_thresholds(age: int, status: str) -> None:
    d = NOW - timedelta(days=age)
    c, doc = one(f"plain note [verified: {d.isoformat()}]")
    f = assess(c, doc, NOW, CFG)
    assert f.status == status and f.age_days == age and not f.must_reverify


@pytest.mark.parametrize(("age", "flag"), [(0, False), (30, False), (31, True), (400, True)])
def test_volatile_window_boundary(age: int, flag: bool) -> None:
    d = NOW - timedelta(days=age)
    c, doc = one(f"- Day pass currently costs $18 [verified: {d.isoformat()}]")
    f = assess(c, doc, NOW, CFG)
    assert f.volatile and f.must_reverify is flag
    if flag:
        assert f.status == STALE and "re-verify" in f.note()


def test_volatile_window_is_configurable() -> None:
    c, doc = one("- Price $5 [verified: 2026-09-01]")
    assert assess(c, doc, NOW, FreshnessConfig(volatile_window_days=60)).must_reverify is False
    assert assess(c, doc, NOW, FreshnessConfig(volatile_window_days=7)).must_reverify is True


def test_future_date_counts_as_age_zero() -> None:
    c, doc = one("note [verified: 2027-01-01]")
    f = assess(c, doc, NOW, CFG)
    assert f.age_days == 0 and f.status == FRESH and f.decay == 1.0


def test_date_priority_inline_then_front_matter_then_mtime() -> None:
    doc = parse("a.md", "---\nupdated: 2026-01-01\n---\nA [verified: 2026-05-05]\n\nB\n", epoch(date(2025, 1, 1)))
    assert effective_date(doc.chunks[0], doc) == (date(2026, 5, 5), "inline")
    assert effective_date(doc.chunks[1], doc) == (date(2026, 1, 1), "front-matter:updated")
    doc2 = parse("b.md", "C\n", epoch(date(2025, 1, 1)))
    assert effective_date(doc2.chunks[0], doc2) == (date(2025, 1, 1), "mtime")


def test_unknown_date_is_stale_and_volatile_is_flagged() -> None:
    c, doc = one("currently $5")
    f = assess(c, doc, NOW, CFG)
    assert f.age_days is None and f.status == STALE and f.must_reverify and f.note() == "age unknown"


@pytest.mark.parametrize(
    "text",
    [
        "It currently opens at 9",
        "as of June the lease is 1200",
        "Costs $40",
        "about 30 EUR a month",
        "The price went up",
        "Hours: 9-5",
        "Status: waitlist",
        "tickets available on Fridays",
        "open until 10pm",
        "out of stock again",
    ],
)
def test_volatile_heuristic_matches(text: str) -> None:
    c, doc = one(text + " [verified: 2026-01-01]")
    assert assess(c, doc, NOW, CFG).volatile


@pytest.mark.parametrize("text", ["Mara prefers morning meetings", "Project lead: Sam", "Lives in Fenby"])
def test_non_volatile_text(text: str) -> None:
    c, doc = one(text + " [verified: 2026-01-01]")
    assert not assess(c, doc, NOW, CFG).volatile


def test_heuristic_can_be_disabled_but_explicit_tags_still_count() -> None:
    cfg = FreshnessConfig(detect_volatile=False)
    c, doc = one("Costs $40 [verified: 2026-01-01]")
    assert not assess(c, doc, NOW, cfg).volatile
    c, doc = one("Costs $40 [volatile] [verified: 2026-01-01]")
    assert assess(c, doc, NOW, cfg).volatile
    doc = parse("a.md", "---\nvolatile: true\n---\nplain [verified: 2026-01-01]\n")
    assert assess(doc.chunks[0], doc, NOW, cfg).volatile


def test_decay_halves_at_half_life() -> None:
    d = NOW - timedelta(days=180)
    c, doc = one(f"x [verified: {d.isoformat()}]")
    assert assess(c, doc, NOW, CFG).decay == pytest.approx(0.5)


def test_mtime_to_date_is_utc() -> None:
    # 2026-03-01 23:30 in New York is already 2026-03-02 in UTC.
    ny = timezone(timedelta(hours=-5))
    ts = datetime(2026, 3, 1, 23, 30, tzinfo=ny).timestamp()
    assert mtime_to_date(ts) == date(2026, 3, 2)


@pytest.mark.parametrize("bad", [0, -5, 1e20])
def test_mtime_to_date_rejects_garbage(bad: float) -> None:
    assert mtime_to_date(bad) is None


def test_leap_day_dates() -> None:
    c, doc = one("x [verified: 2024-02-29]")
    assert assess(c, doc, date(2025, 3, 1), CFG).age_days == 366
