import json
from datetime import date
from pathlib import Path

import pytest

from plainmem import Memory, engine_from_texts
from plainmem.cli import EXIT_OK, main
from plainmem.markdown import parse
from plainmem.mcp_server import tool_diff, tool_explain, tool_search
from plainmem.meta import FactMeta, parse_tag, split_line, strip_tags

from .conftest import NOW, write

ORION = "---\nverified: 2025-11-02\n---\n# Orion\n\n- Project lead: Dana Whit\n- Deploy region: us-east-1\n"


def _mem(tmp_path: Path, files: dict[str, str], when: date = date(2026, 9, 1)) -> Memory:
    root = tmp_path / "n"
    for rel, text in files.items():
        write(root, rel, text, when=when)
    return Memory(root)


def _log(*days: tuple[str, str]) -> str:
    return "# Log\n" + "".join(f"\n## {d}\n\n{body}\n" for d, body in days)


# --- syntax -----------------------------------------------------------------


def test_parse_tag_fields_in_any_order() -> None:
    m = parse_tag("from 2026-08-14, tool, observed")
    assert m == FactMeta(authority="observed", source="tool", valid_from=date(2026, 8, 14))
    m = parse_tag("explicit, user, until 2026-12-31, supersedes Orion project lead")
    assert m is not None and m.valid_until == date(2026, 12, 31) and m.supersedes == "Orion project lead"


@pytest.mark.parametrize(
    "body",
    ["", "x", "explicit, explicit", "explicit, banana", "from 2026-02-30", "from 2026-09-01, until 2026-08-01"],
)
def test_parse_tag_rejects_anything_else(body: str) -> None:
    assert parse_tag(body) is None


def test_prose_braces_are_left_alone() -> None:
    assert split_line("- Template: {name} {x}") == ("- Template: {name} {x}", None)
    assert strip_tags("use {a, b} here\n- Lead: Sam {explicit, user}") == "use {a, b} here\n- Lead: Sam"
    # only at the end of a line
    assert split_line("- Lead {explicit} Sam")[1] is None


def test_tag_is_stripped_from_text_values_and_index() -> None:
    eng = engine_from_texts({"o.md": "# Orion\n\n- Project lead: Sam Okafor {explicit, user}\n"})
    assert eng.chunks[0].clean_text() == "- Project lead: Sam Okafor"
    (a,) = eng.assertions[0]
    assert a.value == "sam okafor" and a.raw_value == "Sam Okafor"
    assert a.meta.authority == "explicit" and a.meta.source == "user"
    assert "explicit" not in eng.tokens[0] and "user" not in eng.tokens[0]


def test_untagged_lines_unchanged() -> None:
    doc = parse("o.md", ORION)
    assert all("{" not in c.clean_text() for c in doc.chunks)
    eng = engine_from_texts({"o.md": ORION})
    assert all(a.meta == FactMeta() for al in eng.assertions for a in al)


# --- resolution -------------------------------------------------------------


def test_authority_breaks_a_same_date_tie() -> None:
    log = _log(
        (
            "2026-09-01",
            "- Orion deploy region: eu-west-2 {inferred, agent}\n- Orion deploy region: ap-south-1 {explicit, user}",
        )
    )
    eng = engine_from_texts({"orion.md": ORION, "log.md": log})
    (c,) = [c for c in eng.conflicts if "region" in c.key]
    assert c.resolved and c.values[c.winner] == "ap-south-1"


def test_untagged_same_date_stays_unresolved() -> None:
    log = _log(("2026-09-01", "- Orion deploy region: eu-west-2\n- Orion deploy region: ap-south-1 {explicit, user}"))
    eng = engine_from_texts({"orion.md": ORION, "log.md": log})
    (c,) = [c for c in eng.conflicts if "region" in c.key]
    assert not c.resolved and c.reason == "same-date"


def test_inferred_never_silently_replaces_explicit() -> None:
    log = _log(
        ("2026-03-01", "- Orion project lead: Sam Okafor {explicit, user}"),
        ("2026-09-01", "- Orion project lead: Kai Moss {inferred, agent}"),
    )
    eng = engine_from_texts({"orion.md": ORION, "log.md": log})
    (c,) = [c for c in eng.conflicts if "lead" in c.key]
    assert not c.resolved and c.reason == "inferred-over-explicit"
    assert not eng.superseded_by  # nothing is demoted while contested


def test_from_tag_backdates_a_change(tmp_path: Path) -> None:
    log = _log(
        ("2026-08-10", "- Orion project lead: Sam Okafor"),
        ("2026-08-20", "- Orion project lead: Kai Moss {explicit, user, from 2026-08-01}"),
    )
    mem = _mem(tmp_path, {"orion.md": ORION, "log.md": log})
    f = mem.explain("Orion project lead", now=NOW)["fact"]
    # Kai took effect on 08-01, before Sam's 08-10 entry, so Sam is the current value
    assert f["current"]["value"] == "Sam Okafor"
    kai = next(s for s in f["superseded"] if s["value"] == "Kai Moss")
    assert kai["as_of"] == "2026-08-01" and kai["date_source"] == "tag:from" and kai["valid_from"] == "2026-08-01"


def test_supersedes_override_catches_an_update_without_key_words(tmp_path: Path) -> None:
    plain = _log(("2026-08-14", "- Priya Nandakumar took over from Dana on Orion."))
    f = _mem(tmp_path / "a", {"orion.md": ORION, "log.md": plain}).explain("Orion project lead", now=NOW)["fact"]
    assert f["current"]["value"] == "Dana Whit"  # the documented limit: no shared key wording, no supersession
    tagged = _log(
        (
            "2026-08-14",
            "- Priya Nandakumar took over from Dana on Orion {explicit, user, supersedes Orion project lead}",
        )
    )
    mem = _mem(tmp_path / "b", {"orion.md": ORION, "log.md": tagged})
    f = mem.explain("Orion project lead", now=NOW)["fact"]
    assert f["current"]["value"] == "Priya Nandakumar took over from Dana on Orion"
    assert f["current"]["cite"] == "log.md:5" and f["superseded"][0]["value"] == "Dana Whit"


def test_supersedes_with_key_value_line_uses_the_value() -> None:
    log = _log(("2026-08-14", "- Owner now: Priya {supersedes Orion project lead}"))
    eng = engine_from_texts({"orion.md": ORION, "log.md": log})
    (c,) = [c for c in eng.conflicts if "lead" in c.key]
    assert c.values[c.winner] == "Priya"


# --- expiry -----------------------------------------------------------------


def test_until_expires_a_fact(tmp_path: Path) -> None:
    log = _log(("2026-06-01", "- Orion code freeze: on {explicit, user, until 2026-07-31}"))
    mem = _mem(tmp_path, {"orion.md": ORION, "log.md": log})
    hit = next(h for h in mem.search("orion code freeze", now=NOW).to_dict()["results"] if "freeze" in h["text"])
    assert hit["status"] == "EXPIRED" and hit["valid_until"] == "2026-07-31"
    assert mem.explain("orion code freeze", now=NOW)["fact"]["status"] == "expired"
    assert mem.explain("orion code freeze", now=NOW, as_of=date(2026, 7, 1))["fact"]["status"] == "known"
    f = mem.explain("orion code freeze", now=NOW, as_of=date(2026, 8, 5))["fact"]
    assert f["status"] == "expired" and f["timeline"] == [
        {"value": "on", "from": "2026-06-01", "to": "2026-07-31", "present": False}
    ]


# --- as_of ------------------------------------------------------------------

HIST = _log(
    ("2026-03-01", "- Orion project lead: Sam Okafor {explicit, user}"),
    ("2026-07-01", "- Orion project lead: Kai Moss {observed, tool}"),
)


def test_explain_as_of_walks_the_chain(tmp_path: Path) -> None:
    mem = _mem(tmp_path, {"orion.md": ORION, "log.md": HIST})
    q = "Who is the Orion project lead?"
    expect = {date(2025, 12, 1): "Dana Whit", date(2026, 4, 1): "Sam Okafor", date(2026, 8, 1): "Kai Moss"}
    for when, value in expect.items():
        r = mem.explain(q, now=NOW, as_of=when)
        assert r["as_of"] == when.isoformat()
        assert r["fact"]["current"]["value"] == value and r["fact"]["status"] == "known", when
    r = mem.explain(q, now=NOW, as_of=date(2026, 4, 1))["fact"]
    assert [s["value"] for s in r["superseded"]] == ["Dana Whit"]
    assert [s["value"] for s in r["changed_after"]] == ["Kai Moss"]
    assert r["current"]["authority"] == "explicit" and r["current"]["source"] == "user"


def test_explain_as_of_before_anything_was_recorded(tmp_path: Path) -> None:
    mem = _mem(tmp_path, {"orion.md": ORION, "log.md": HIST})
    r = mem.explain("Orion project lead", now=NOW, as_of=date(2025, 1, 1))
    # the dated entries all start later; nothing is found at that date
    assert r["no_match"] or r["fact"] is None or r["fact"]["status"] == "none"


def test_explain_as_of_with_only_mtime_dates_is_honest(tmp_path: Path) -> None:
    undated = "# Orion\n\n- Project lead: Dana Whit\n"
    mem = _mem(tmp_path, {"orion.md": undated, "log.md": _log(("2026-08-14", "- Orion project lead: Sam Okafor"))})
    # before the log entry, Dana's only date is the file save date (2026-09-01): cannot tell
    r = mem.explain("Orion project lead", now=NOW, as_of=date(2026, 6, 1))
    assert r["fact"]["status"] == "unknown" and r["fact"]["current"] is None
    # after the file was saved Dana's entry exists, but its start date is still a guess
    r = mem.explain("Orion project lead", now=NOW, as_of=date(2026, 9, 15))
    assert r["fact"]["status"] == "uncertain" and r["fact"]["current"]["date_source"] == "mtime"


def test_search_as_of_drops_later_notes_and_resupersedes(tmp_path: Path) -> None:
    mem = _mem(tmp_path, {"orion.md": ORION, "log.md": HIST})
    now = mem.search("Orion project lead", now=NOW).to_dict()
    assert now["as_of"] is None and now["results"][0]["text"].endswith("Kai Moss")
    then = mem.search("Orion project lead", now=NOW, as_of=date(2026, 4, 1)).to_dict()
    assert then["as_of"] == "2026-04-01"
    texts = [r["text"] for r in then["results"]]
    assert not any("Kai Moss" in t for t in texts)
    top = then["results"][0]
    assert top["text"].endswith("Sam Okafor") and top["status"] != "SUPERSEDED"
    assert top["authority"] == "explicit" and top["facts"][0]["source"] == "user"
    dana = next(r for r in then["results"] if "Dana" in r["text"])
    assert dana["status"] == "SUPERSEDED"


def test_search_as_of_bm25_mode_also_filters(tmp_path: Path) -> None:
    mem = _mem(tmp_path, {"orion.md": ORION, "log.md": HIST})
    res = mem.search("Orion project lead", now=NOW, mode="bm25", as_of=date(2026, 4, 1)).to_dict()["results"]
    assert res and not any("Kai" in r["text"] for r in res)


# --- surfaces ---------------------------------------------------------------


def test_diff_rows_carry_provenance(tmp_path: Path) -> None:
    mem = _mem(tmp_path, {"orion.md": ORION, "log.md": HIST})
    d = mem.diff(date(2026, 6, 1))
    (row,) = d["updated"]
    assert row["value"] == "Kai Moss" and row["authority"] == "observed" and row["source"] == "tool"
    assert row["previous"]["authority"] == "explicit"


def test_cli_as_of_and_provenance_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mem = _mem(tmp_path, {"orion.md": ORION, "log.md": HIST})
    base = ["--root", str(mem.root), "--now", "2026-09-29"]
    assert main([*base, "explain", "Orion", "project", "lead", "--as-of", "2026-04-01"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "(as of 2026-04-01)" in out and "value then  Sam Okafor" in out and "explicit, user" in out
    assert "later       Kai Moss" in out
    assert main([*base, "search", "Orion", "project", "lead", "--as-of", "2026-04-01", "--json"]) == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["as_of"] == "2026-04-01"
    assert main([*base, "search", "Orion", "project", "lead"]) == EXIT_OK
    assert "{observed, tool}" in capsys.readouterr().out
    assert main([*base, "diff", "--since", "2026-06-01"]) == EXIT_OK
    assert "observed, tool" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main([*base, "search", "x", "--as-of", "2026-13-01"])


def test_cli_explain_reports_no_value_yet(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    undated = "# Orion\n\n- Project lead: Dana Whit\n"
    mem = _mem(tmp_path, {"orion.md": undated})
    base = ["--root", str(mem.root), "--now", "2026-09-29"]
    main([*base, "explain", "Orion", "project", "lead", "--as-of", "2026-06-01"])
    assert "UNKNOWN" in capsys.readouterr().out


def test_mcp_tools_take_as_of_and_diff(tmp_path: Path) -> None:
    mem = _mem(tmp_path, {"orion.md": ORION, "log.md": HIST})
    assert tool_search(mem, "Orion project lead", as_of="2026-04-01")["as_of"] == "2026-04-01"
    assert tool_explain(mem, "Orion project lead", as_of="2026-04-01")["fact"]["current"]["value"] == "Sam Okafor"
    assert tool_diff(mem, "2026-06-01")["updated"][0]["source"] == "tool"
    with pytest.raises(ValueError):
        tool_search(mem, "x", as_of="April")
