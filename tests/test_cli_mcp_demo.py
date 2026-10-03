import json
import sys
from datetime import date
from pathlib import Path

import pytest

from plainmem import Memory
from plainmem.cli import EXIT_CORRUPT, EXIT_NO_MATCH, EXIT_OK, EXIT_USAGE, main
from plainmem.mcp_server import tool_add, tool_search, tool_stale

from .conftest import NOW

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "demo"))
import logic  # noqa: E402


def run(capsys, *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def test_cli_index_and_search(notes: Path, capsys) -> None:
    code, out = run(capsys, "--root", str(notes), "index")
    assert code == EXIT_OK and json.loads(out)["files"] == 3
    code, out = run(capsys, "--root", str(notes), "--now", "2026-09-29", "search", "orion", "project", "lead")
    assert code == EXIT_OK and "journal/2026-08-14.md:3" in out and "superseded by" in out


def test_cli_search_json_proves_it_searched(notes: Path, capsys) -> None:
    code, out = run(capsys, "--root", str(notes), "search", "--json", "zebra")
    data = json.loads(out)
    assert code == EXIT_NO_MATCH
    assert data["no_match"] is True and data["results"] == []
    assert data["searched_at"] and data["index_version"] and data["files_indexed"] == 3


def test_cli_search_json_fields(notes: Path, capsys) -> None:
    _, out = run(capsys, "--root", str(notes), "--now", "2026-09-29", "search", "--json", "day", "pass")
    r = json.loads(out)["results"][0]
    assert r["cite"] == "places/gym.md:3" and r["must_reverify"] and r["status"] == "STALE" and r["volatile"]


def test_cli_bm25_mode(notes: Path, capsys) -> None:
    _, out = run(capsys, "--root", str(notes), "search", "--json", "--mode", "bm25", "orion")
    assert all(r["status"] == "UNKNOWN" for r in json.loads(out)["results"])


def test_cli_corrupt_index_exit_code(notes: Path, capsys) -> None:
    run(capsys, "--root", str(notes), "index")
    (notes / ".plainmem/index.json").write_text("{broken")
    code = main(["--root", str(notes), "search", "orion"])
    assert code == EXIT_CORRUPT
    assert "Refusing to search" in capsys.readouterr().err
    assert main(["--root", str(notes), "index", "--rebuild"]) == EXIT_OK


def test_cli_add_conflicts_stale_stats(notes: Path, capsys) -> None:
    code, out = run(capsys, "--root", str(notes), "add", "--date", "2026-09-28", "Orion", "designer:", "Kai", "Moss")
    assert code == EXIT_OK and "log.md" in out
    _, out = run(capsys, "--root", str(notes), "conflicts")
    assert "SUPERSEDED  projects/orion.md:9  Lee Park" in out and "2 conflicting keys" in out
    _, out = run(capsys, "--root", str(notes), "conflicts", "--json")
    assert len(json.loads(out)) == 2
    _, out = run(capsys, "--root", str(notes), "--now", "2026-09-29", "stale", "--json")
    assert [r["cite"] for r in json.loads(out)] == ["places/gym.md:3"]
    _, out = run(capsys, "--root", str(notes), "--now", "2026-09-29", "stale")
    assert "1 volatile facts" in out
    _, out = run(capsys, "--root", str(notes), "stats", "--json")
    assert json.loads(out)["files"] == 4


def test_cli_rotate(tmp_path: Path, capsys) -> None:
    run(capsys, "--root", str(tmp_path), "add", "--date", "2026-01-01", "old")
    run(capsys, "--root", str(tmp_path), "add", "--date", "2026-09-28", "new")
    code, out = run(capsys, "--root", str(tmp_path), "--now", "2026-09-29", "rotate", "--keep-days", "30")
    assert code == EXIT_OK and json.loads(out)["archived"] == 1
    assert (tmp_path / "archive/log-2026-01.md").exists()


def test_cli_bad_root_and_bad_date(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path / "nope"), "stats"]) == EXIT_USAGE
    with pytest.raises(SystemExit):
        main(["--now", "2026-13-01", "stats"])
    with pytest.raises(SystemExit):
        main(["--now", "yesterday", "stats"])


def test_mcp_tools(notes: Path) -> None:
    mem = Memory(notes)
    res = tool_search(mem, "orion lead", k=500)
    assert res["no_match"] is False and "searched_at" in res and len(res["results"]) <= 50
    assert tool_search(mem, "zebra")["no_match"] is True
    assert tool_add(mem, "Orion designer: Kai Moss")["appended_to"] == "log.md"
    assert tool_stale(mem)["count"] >= 1


# --- demo logic ----------------------------------------------------------------


@pytest.fixture(scope="module")
def base():
    return logic.load_base()


def test_demo_make_note_validation() -> None:
    path, md = logic.make_note("  Orion project lead:   Kai  ", date(2026, 9, 1), 0)
    assert path == "visitor/note-01.md" and md == "# 2026-09-01\n\n- Orion project lead: Kai\n"
    with pytest.raises(ValueError):
        logic.make_note("   ", NOW, 0)
    with pytest.raises(ValueError):
        logic.make_note("x" * 500, NOW, 0)
    with pytest.raises(ValueError):
        logic.make_note("ok", NOW, logic.MAX_NOTES)
    assert logic.make_note("## # > heading?", NOW, 0)[1].endswith("- heading?\n")


def test_demo_supersession_by_visitor_note(base) -> None:
    texts, mtimes, queries = base
    q = next(q for q in queries if q.qtype == "superseded" and "lead" in q.query)
    project = q.query.split()[3]
    path, md = logic.make_note(f"{project} project lead: Visitor Person", NOW, 0)
    eng = logic.build_engine(texts, mtimes, {path: md})
    rows = logic.run_query(eng, q.query, "full")
    assert rows[0].cite == f"{path}:3"
    assert any(r.status == "SUPERSEDED" for r in rows)
    conflicts = logic.visitor_conflicts(eng)
    assert conflicts and conflicts[0]["current"].startswith(path)


def test_demo_rows_and_html_escape(base) -> None:
    texts, mtimes, _ = base
    eng = logic.build_engine(texts, mtimes, {"visitor/x.md": "# 2026-09-29\n\n- <script>alert(1)</script> zebra\n"})
    [row] = logic.run_query(eng, "zebra", "full")
    html_out = logic.row_html(row)
    assert "<script>" not in html_out and "&lt;script&gt;" in html_out
    assert logic.run_query(eng, "   ", "full") == []
    assert all(r.status == "BM25" for r in logic.run_query(eng, "orion", "bm25"))


def test_demo_sample_queries_cover_types(base) -> None:
    ex = logic.sample_queries(base[2])
    assert len(ex) == 12 and len(set(ex)) == 12


def test_demo_badges() -> None:
    assert "#6e40c9" in logic.badge_html("SUPERSEDED")
    assert "&lt;b&gt;" in logic.badge_html("<b>")


def test_mcp_server_registers_tools(notes: Path) -> None:
    pytest.importorskip("mcp")
    import asyncio

    from plainmem.mcp_server import build_server

    server = build_server(Memory(notes))
    names = sorted(t.name for t in asyncio.run(server.list_tools()))
    assert names == ["add", "explain", "search", "stale"]
    content = asyncio.run(server.call_tool("search", {"query": "zebra"}))
    assert "no_match" in str(content)
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    a = tools["explain"].annotations
    assert tools["explain"].title == "Explain a fact"
    assert (a.read_only_hint, a.destructive_hint, a.idempotent_hint, a.open_world_hint) == (True, False, True, False)
