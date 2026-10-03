import json
from datetime import date
from pathlib import Path

from plainmem import Memory
from plainmem.cli import EXIT_NO_MATCH, EXIT_OK, main
from plainmem.mcp_server import tool_explain

from .conftest import NOW, write


def _mem(tmp_path: Path, files: dict[str, str]) -> Memory:
    root = tmp_path / "n"
    for rel, text in files.items():
        write(root, rel, text, when=date(2026, 9, 1))
    return Memory(root)


ORION = "---\nverified: 2025-11-02\n---\n# Orion\n\n- Project lead: Dana Whit\n- Budget: $40,000\n"
LOG = "# Log\n\n## 2026-08-14\n\n- Orion project lead: Sam Okafor, Dana moved to Atlas.\n"
LOG2 = LOG + "\n## 2026-09-20\n\n- Orion project lead: Kai Moss\n"


def test_explain_zero_supersessions(tmp_path: Path) -> None:
    r = _mem(tmp_path, {"orion.md": ORION}).explain("what is the orion budget", now=NOW)
    f = r["fact"]
    assert r["no_match"] is False and r["no_fact"] is False
    assert f["current"]["value"] == "$40,000" and f["current"]["cite"] == "orion.md:7"
    assert f["superseded"] == []
    assert [t["value"] for t in f["timeline"]] == ["$40,000"] and f["timeline"][0]["present"]
    assert f["freshness"]["status"] == "STALE" and f["freshness"]["must_reverify"]  # dollar amounts are volatile


def test_explain_one_supersession(tmp_path: Path) -> None:
    f = _mem(tmp_path, {"orion.md": ORION, "log.md": LOG}).explain("Who is the Orion project lead?", now=NOW)["fact"]
    assert f["current"] == {
        "value": "Sam Okafor",
        "cite": "log.md:5",
        "as_of": "2026-08-14",
        "date_source": "heading",
    }
    assert [(s["value"], s["cite"], s["as_of"]) for s in f["superseded"]] == [("Dana Whit", "orion.md:6", "2025-11-02")]
    assert f["timeline"] == [
        {"value": "Dana Whit", "from": "2025-11-02", "to": "2026-08-14", "present": False},
        {"value": "Sam Okafor", "from": "2026-08-14", "to": None, "present": True},
    ]
    assert f["resolved"] is True and f["freshness"]["status"] == "FRESH"


def test_explain_two_supersessions_newest_first(tmp_path: Path) -> None:
    f = _mem(tmp_path, {"orion.md": ORION, "log.md": LOG2}).explain("orion project lead", now=NOW)["fact"]
    assert f["current"]["value"] == "Kai Moss"
    assert [s["value"] for s in f["superseded"]] == ["Sam Okafor", "Dana Whit"]
    assert [t["value"] for t in f["timeline"]] == ["Dana Whit", "Sam Okafor", "Kai Moss"]
    assert f["timeline"][1]["to"] == "2026-09-20"


def test_explain_unresolved_same_date(tmp_path: Path) -> None:
    files = {
        "a.md": "# A\n\n## 2026-08-01\n\n- Atlas owner: Ann\n",
        "b.md": "# B\n\n## 2026-08-01\n\n- Atlas owner: Bob\n",
    }
    f = _mem(tmp_path, files).explain("atlas owner", now=NOW)["fact"]
    assert f["resolved"] is False


def test_explain_no_match_and_no_fact(tmp_path: Path) -> None:
    mem = _mem(tmp_path, {"orion.md": ORION, "n.md": "# Notes\n\nThe build runner was slow on Friday.\n"})
    r = mem.explain("zebra migration", now=NOW)
    assert r["no_match"] is True and r["fact"] is None
    assert r["searched_at"] and r["index_version"]
    r = mem.explain("build runner friday", now=NOW)  # hits exist, none state a keyed fact
    assert r["no_match"] is False and r["no_fact"] is True and r["fact"] is None
    assert r["nearest"] and r["nearest"][0].startswith("n.md:")


def test_diff_added_updated_and_empty_window(tmp_path: Path) -> None:
    mem = _mem(tmp_path, {"orion.md": ORION, "log.md": LOG2})
    d = mem.diff(date(2026, 8, 1))
    assert d["added"] == []
    # one row per key: the value before the window -> the value at the end of it
    assert [(u["label"], u["value"], u["previous"]["value"]) for u in d["updated"]] == [
        ("Orion project lead", "Kai Moss", "Dana Whit")
    ]
    d = mem.diff(date(2026, 8, 1), date(2026, 8, 31))
    assert d["updated"][0]["value"] == "Sam Okafor" and d["updated"][0]["cite"] == "log.md:5"
    d = mem.diff(date(2025, 1, 1), date(2025, 12, 31))
    assert sorted(r["label"] for r in d["added"]) == ["Budget", "Project lead"] and d["updated"] == []
    d = mem.diff(date(2027, 1, 1))
    assert d["added"] == [] and d["updated"] == [] and d["until"] is None


def test_diff_unchanged_value_is_not_an_update(tmp_path: Path) -> None:
    log = "# Log\n\n## 2026-08-14\n\n- Orion budget: $40,000\n"
    d = _mem(tmp_path, {"orion.md": ORION, "log.md": log}).diff(date(2026, 8, 1))
    assert d["added"] == [] and d["updated"] == []


def test_cli_explain_and_diff_json_shapes(tmp_path: Path, capsys) -> None:
    mem = _mem(tmp_path, {"orion.md": ORION, "log.md": LOG})
    base = ["--root", str(mem.root), "--now", "2026-09-29"]
    assert main([*base, "explain", "--json", "orion", "project", "lead"]) == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert {"question", "searched_at", "index_version", "no_match", "no_fact", "fact"} <= out.keys()
    assert {"key", "label", "resolved", "current", "superseded", "timeline", "freshness"} == out["fact"].keys()
    assert main([*base, "diff", "--since", "2026-08-01", "--json"]) == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out.keys() == {"since", "until", "added", "updated", "undated_skipped"}
    assert out["updated"][0]["previous"].keys() == {"value", "cite", "as_of", "date_source"}


def test_cli_explain_text_and_exit_codes(tmp_path: Path, capsys) -> None:
    mem = _mem(tmp_path, {"orion.md": ORION, "log.md": LOG})
    base = ["--root", str(mem.root), "--now", "2026-09-29"]
    assert main([*base, "explain", "Who is the Orion project lead?"]) == EXIT_OK
    text = capsys.readouterr().out
    assert "current     Sam Okafor  (log.md:5, 2026-08-14)" in text
    assert "superseded  Dana Whit  (orion.md:6, 2025-11-02)" in text
    assert "Sam Okafor: 2026-08-14 -> present" in text
    assert main([*base, "explain", "zebra"]) == EXIT_NO_MATCH
    assert "no match" in capsys.readouterr().out
    assert main([*base, "diff", "--since", "2027-01-01"]) == EXIT_OK
    assert "no changes" in capsys.readouterr().out


def test_mcp_tool_explain(tmp_path: Path) -> None:
    res = tool_explain(_mem(tmp_path, {"orion.md": ORION, "log.md": LOG}), "orion project lead")
    assert res["fact"]["current"]["value"] == "Sam Okafor"
