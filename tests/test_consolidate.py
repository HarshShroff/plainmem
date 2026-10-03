from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from plainmem import Memory, engine_from_texts
from plainmem import consolidate as cons
from plainmem.cli import main as cli_main
from plainmem.consolidate_llm import LLMClassifier, build_prompt, parse_verdict
from plainmem.mcp_server import tool_add, tool_candidates

ORION = """---
entity: Orion
updated: 2025-11-02
---
# Orion

- Project lead: Dana Whitfield
- Design reviewer: Omar Haddad
- Deploy region: eu-west-2
"""
ATLAS = "---\nentity: Atlas\n---\n# Atlas\n\n- Project lead: Sam Okafor\n"
NOTE = "Priya Nair took over from Dana Whitfield on Orion."


@pytest.fixture
def mem(tmp_path: Path) -> Memory:
    (tmp_path / "projects").mkdir()
    (tmp_path / "projects" / "orion.md").write_text(ORION)
    (tmp_path / "projects" / "atlas.md").write_text(ATLAS)
    m = Memory(tmp_path)
    m.index()
    return m


def fixed(verdict):  # type: ignore[no-untyped-def]
    calls = []

    def clf(text, cands):  # type: ignore[no-untyped-def]
        calls.append((text, cands))
        return verdict

    clf.calls = calls  # type: ignore[attr-defined]
    return clf


def lead(m: Memory) -> dict:
    return m.explain("Who is the Orion project lead?", now=date(2026, 6, 1))["fact"]["current"]


def test_key_normalization_possessive_and_preposition() -> None:
    text = (
        "# Log\n\n## 2026-01-02\n\n- Orion's project lead: Sam Okafor\n\n## 2026-01-03\n\n"
        "- Project lead for Orion: Dana Lee\n\n## 2026-01-04\n\n- Orion project lead: Priya Nair\n\n"
        "## 2026-01-05\n\n- Orion’s project lead is now Omar Haddad.\n"
    )
    eng = engine_from_texts({"log.md": text})
    keys = {a.key for alist in eng.assertions for a in alist}
    assert keys == {"lead orion project"}
    assert {c.label for c in eng.conflicts} and len(eng.conflicts) == 1


def test_candidates_find_the_fact_and_skip_other_entities(mem: Memory) -> None:
    got = mem.candidates_for(NOTE)
    assert got[0]["key"] == "Orion Project lead" and got[0]["value"] == "Dana Whitfield"
    assert got[0]["cite"] == "projects/orion.md:7"
    assert all(c["key"].startswith("Orion") for c in got)
    assert {c["key"] for c in mem.candidates_for("Priya Nair took over Orion.")} == {
        "Orion Project lead",
        "Orion Design reviewer",
        "Orion Deploy region",
    }
    assert mem.candidates_for("Nothing to see here.") == []


def test_add_supersedes_writes_tag_and_explain_follows_it(mem: Memory) -> None:
    assert lead(mem)["value"] == "Dana Whitfield"
    mem.add(NOTE, when=date(2026, 3, 1), supersedes="Orion Project lead")
    log = (mem.root / "log.md").read_text()
    assert "- Priya Nair took over from Dana Whitfield on Orion. {supersedes Orion Project lead}" in log
    assert lead(mem)["cite"] == "log.md:5"


def test_tag_text_merges_and_rejects() -> None:
    assert cons.tag_text("Sam runs Orion {explicit, user}", "Orion lead") == (
        "Sam runs Orion {explicit, user, supersedes Orion lead}"
    )
    assert cons.tag_text("a\nb", "Orion lead") == "a {supersedes Orion lead}\nb"
    for bad in ("", "a, b", "x{y}", "k" * 61):
        with pytest.raises(ValueError):
            cons.tag_text("Sam runs Orion", bad)
    with pytest.raises(ValueError):
        cons.tag_text("Sam runs Orion {supersedes Orion lead}", "Orion lead")


def test_consolidate_supersedes(mem: Memory) -> None:
    clf = fixed({"relation": "supersedes", "target": "Orion Project lead", "reason": "handover"})
    out = mem.consolidate(NOTE, clf, when=date(2026, 3, 1))
    assert out["wrote_supersedes"] == "Orion Project lead" and out["verdict"]["valid"]
    assert lead(mem)["cite"] == "log.md:5"
    assert clf.calls[0][0] == NOTE and clf.calls[0][1][0]["key"] == "Orion Project lead"
    rec = json.loads((mem.index_file.parent / "consolidation.jsonl").read_text().splitlines()[-1])
    assert rec["wrote_supersedes"] == "Orion Project lead"


@pytest.mark.parametrize(
    ("verdict", "check"),
    [
        ({"relation": "supersedes", "target": "Atlas Project lead"}, "target_in_candidates"),
        ({"relation": "supersedes", "target": "Orion budget"}, "target_in_candidates"),
        ({"relation": "supersedes", "target": None}, "target_in_candidates"),
        ({"relation": "replaces", "target": "Orion Project lead"}, "relation_allowed"),
        ("supersedes Orion Project lead", "shape"),
        (None, "shape"),
    ],
)
def test_bad_verdicts_become_unrelated_and_write_no_tag(mem: Memory, verdict, check) -> None:  # type: ignore[no-untyped-def]
    out = mem.consolidate(NOTE, fixed(verdict), when=date(2026, 3, 1))
    assert out["verdict"]["relation"] == "unrelated" and out["verdict"]["failed_check"] == check
    assert out["wrote_supersedes"] is None
    assert "{" not in (mem.root / "log.md").read_text()
    assert lead(mem)["value"] == "Dana Whitfield"
    rec = json.loads((mem.index_file.parent / "consolidation.jsonl").read_text().splitlines()[-1])
    assert rec["verdict"]["failed_check"] == check


@pytest.mark.parametrize("relation", ["insufficient", "unrelated", "refines", "contradicts"])
def test_only_supersedes_writes(mem: Memory, relation: str) -> None:
    target = "Orion Project lead" if relation in cons.TARGETED else None
    out = mem.consolidate(NOTE, fixed({"relation": relation, "target": target}), when=date(2026, 3, 1))
    assert out["verdict"]["relation"] == relation and out["wrote_supersedes"] is None
    assert lead(mem)["value"] == "Dana Whitfield"


def test_insufficient_never_keeps_a_target(mem: Memory) -> None:
    out = mem.judge(NOTE, fixed({"relation": "insufficient", "target": "Orion Project lead"}))
    assert out["verdict"]["relation"] == "insufficient" and out["verdict"]["target"] is None


def test_target_must_still_be_in_effect(tmp_path: Path) -> None:
    (tmp_path / "orion.md").write_text(
        "---\nentity: Orion\n---\n# Orion\n\n- Project lead: Dana Whitfield {explicit, user, until 2026-01-31}\n"
    )
    m = Memory(tmp_path)
    verdict = {"relation": "supersedes", "target": "Orion Project lead"}
    assert m.judge(NOTE, fixed(verdict), today=date(2026, 1, 15))["verdict"]["relation"] == "supersedes"
    v = m.judge(NOTE, fixed(verdict), today=date(2026, 3, 1))["verdict"]
    assert v["relation"] == "unrelated" and v["failed_check"] == "target_current"


def test_note_must_supply_a_value(mem: Memory) -> None:
    v = mem.judge(
        "Orion project lead: Dana Whitfield.", fixed({"relation": "supersedes", "target": "Orion Project lead"})
    )
    assert v["verdict"]["failed_check"] == "supplies_value" and v["verdict"]["relation"] == "unrelated"


def test_classifier_errors_and_no_candidates(mem: Memory) -> None:
    def boom(text, cands):  # type: ignore[no-untyped-def]
        raise RuntimeError("down")

    out = mem.consolidate(NOTE, boom, when=date(2026, 3, 1))
    assert out["verdict"]["failed_check"] == "classifier_error" and out["wrote_supersedes"] is None
    clf = fixed({"relation": "supersedes", "target": "Orion Project lead"})
    out = mem.consolidate("Lunch was fine.", clf)
    assert out["called"] is False and clf.calls == [] and out["verdict"]["relation"] == "unrelated"


def test_parse_verdict_is_strict() -> None:
    ok = '{"relation": "supersedes", "target": "Orion Project lead", "reason": "x"}'
    assert parse_verdict(ok)["target"] == "Orion Project lead"
    assert parse_verdict("```json\n" + ok + "\n```")["relation"] == "supersedes"
    for bad in ["", "supersedes", "Sure! " + ok, '{"target": "x"}', '{"relation": 1}', '["supersedes"]',
                '{"relation": "supersedes", "target": 3}', None]:  # fmt: skip
        assert parse_verdict(bad) is None, bad


def test_llm_classifier_unparsable_and_failed_calls_are_unrelated(mem: Memory) -> None:
    clf = LLMClassifier(lambda prompt: "I think it supersedes the lead.")
    out = mem.consolidate(NOTE, clf, when=date(2026, 3, 1))
    assert out["verdict"]["relation"] == "unrelated" and out["wrote_supersedes"] is None
    assert clf.calls == 1 and clf.failures == 1

    def down(prompt: str) -> str:
        raise TimeoutError("slow")

    clf2 = LLMClassifier(down)
    assert clf2(NOTE, [])["relation"] == "unrelated" and clf2.failures == 1
    seen = []
    clf3 = LLMClassifier(lambda p: seen.append(p) or '{"relation": "supersedes", "target": "Orion Project lead"}')
    assert mem.consolidate(NOTE, clf3, when=date(2026, 3, 2))["wrote_supersedes"] == "Orion Project lead"
    assert "Orion Project lead: Dana Whitfield" in seen[0] and NOTE in seen[0]


def test_build_prompt_lists_candidates() -> None:
    p = build_prompt("a  note\nhere", [{"key": "Orion lead", "value": "Dana"}])
    assert "New note: a note here" in p and "- Orion lead: Dana" in p


def test_core_does_not_import_llm_module() -> None:
    code = "import sys, plainmem, plainmem.memory; print('plainmem.consolidate_llm' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"


def test_mcp_tools_add_supersedes_and_candidates(mem: Memory) -> None:
    c = tool_candidates(mem, NOTE, k=2)
    assert c["count"] == 2 and c["candidates"][0]["key"] == "Orion Project lead"
    out = tool_add(mem, NOTE, supersedes="Orion Project lead")
    assert out == {"appended_to": "log.md", "supersedes": "Orion Project lead"}
    assert "{supersedes Orion Project lead}" in (mem.root / "log.md").read_text()
    assert tool_add(mem, "plain note")["supersedes"] is None


def test_mcp_candidates_tool_is_read_only(mem: Memory) -> None:
    pytest.importorskip("mcp")
    import asyncio

    from plainmem.mcp_server import build_server

    tools = {t.name: t for t in asyncio.run(build_server(mem).list_tools())}
    a = tools["candidates"].annotations
    assert (a.read_only_hint, a.destructive_hint, a.idempotent_hint) == (True, False, True)
    schema = getattr(tools["add"], "input_schema", None) or tools["add"].inputSchema
    assert "supersedes" in schema["properties"]
    assert tools["add"].annotations.read_only_hint is False


def test_cli_candidates_and_add_supersedes(mem: Memory, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(mem.root)
    assert cli_main(["--root", root, "candidates", "--json", NOTE]) == 0
    assert json.loads(capsys.readouterr().out)[0]["key"] == "Orion Project lead"
    assert cli_main(["--root", root, "add", "--supersedes", "Orion Project lead", NOTE]) == 0
    assert "{supersedes Orion Project lead}" in (mem.root / "log.md").read_text()
