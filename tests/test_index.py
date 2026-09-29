import json
import os
import time
from pathlib import Path

import pytest

from plainmem import IndexCorruptError, IndexMissingError, Memory
from plainmem import index as idx

from .conftest import NOW, write


def test_build_save_load_roundtrip(notes: Path) -> None:
    mem = Memory(notes)
    st = mem.index()
    assert st["added"] == 3 and st["files"] == 3 and st["bytes"] > 0
    data = idx.load(mem.index_file)
    assert data.version == st["version"]
    assert sum(len(d.chunks) for d in data.docs.values()) == st["chunks"]
    fresh = Memory(notes)
    fresh.load()
    a = [h.chunk.cite for h in fresh.search("orion lead", now=NOW, refresh=False).hits]
    b = [h.chunk.cite for h in mem.search("orion lead", now=NOW, refresh=False).hits]
    assert a == b


def test_incremental_update_counts(notes: Path) -> None:
    mem = Memory(notes)
    mem.index()
    assert mem.index()["unchanged"] == 3
    write(notes, "new.md", "brand new note\n")
    (notes / "places/gym.md").unlink()
    p = notes / "projects/orion.md"
    p.write_text(p.read_text() + "\nextra line\n")
    st = mem.index()
    assert (st["added"], st["updated"], st["removed"], st["unchanged"]) == (1, 1, 1, 1)


def test_touch_without_change_is_unchanged_by_hash(notes: Path) -> None:
    mem = Memory(notes)
    v1 = mem.index()["version"]
    p = notes / "projects/orion.md"
    os.utime(p, (time.time() + 100, time.time() + 100))
    st = mem.index()
    assert st["unchanged"] == 3 and st["version"] == v1


def test_version_changes_with_content(notes: Path) -> None:
    mem = Memory(notes)
    v1 = mem.index()["version"]
    write(notes, "x.md", "x\n")
    assert mem.index()["version"] != v1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s[: len(s) // 2],
        lambda s: s.replace("Dana", "Evil"),
        lambda s: json.dumps({**json.loads(s), "schema": 999}),
        lambda s: "not json at all",
        lambda s: "[]",
        lambda s: json.dumps({"schema": 1, "checksum": "x"}),
    ],
    ids=["truncated", "edited", "schema", "garbage", "wrong-type", "missing-payload"],
)
def test_corrupt_index_fails_closed(notes: Path, mutate) -> None:
    mem = Memory(notes)
    mem.index()
    mem.index_file.write_text(mutate(mem.index_file.read_text()))
    with pytest.raises(IndexCorruptError):
        Memory(notes).search("orion")


def test_token_count_mismatch_is_corrupt(notes: Path) -> None:
    mem = Memory(notes)
    mem.index()
    outer = json.loads(mem.index_file.read_text())
    payload = json.loads(outer["payload"])
    first = next(iter(payload["docs"]))
    payload["docs"][first]["tokens"].append(["extra"])
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    import hashlib

    outer["payload"], outer["checksum"] = body, hashlib.sha256(body.encode()).hexdigest()
    mem.index_file.write_text(json.dumps(outer))
    with pytest.raises(IndexCorruptError, match="mismatch"):
        Memory(notes).load()


def test_non_utf8_index_is_corrupt(notes: Path) -> None:
    mem = Memory(notes)
    mem.index()
    mem.index_file.write_bytes(b"\xff\xfe\x00garbage")
    with pytest.raises(IndexCorruptError):
        Memory(notes).load()


def test_rebuild_recovers_from_corruption(notes: Path) -> None:
    mem = Memory(notes)
    mem.index()
    mem.index_file.write_text("{")
    st = Memory(notes).index(rebuild=True)
    assert st["added"] == 3
    assert not Memory(notes).search("orion", now=NOW).no_match


def test_missing_index_raises_on_load(tmp_path: Path) -> None:
    with pytest.raises(IndexMissingError):
        Memory(tmp_path).load()


def test_first_search_builds_index(notes: Path) -> None:
    mem = Memory(notes)
    assert not mem.index_file.exists()
    assert not mem.search("orion", now=NOW).no_match
    assert mem.index_file.exists()


def test_search_refresh_sees_new_files(notes: Path) -> None:
    mem = Memory(notes)
    assert mem.search("zebra", now=NOW).no_match
    write(notes, "z.md", "a zebra note\n")
    assert not mem.search("zebra", now=NOW).no_match


def test_empty_corpus(tmp_path: Path) -> None:
    resp = Memory(tmp_path).search("anything", now=NOW)
    assert resp.no_match and resp.files_indexed == 0 and resp.chunks_indexed == 0


def test_hidden_and_tool_dirs_are_skipped(notes: Path) -> None:
    write(notes, ".git/x.md", "secret git note\n")
    write(notes, "node_modules/pkg/readme.md", "vendored\n")
    write(notes, ".obsidian/y.md", "config\n")
    write(notes, "notes.txt", "not markdown\n")
    Memory(notes).index()
    assert set(idx.load(Memory(notes).index_file).docs) == {
        "projects/orion.md",
        "journal/2026-08-14.md",
        "places/gym.md",
    }


def test_oversized_file_is_skipped_and_reported(notes: Path) -> None:
    write(notes, "big.md", "word " * 1000)
    data, st = idx.build(notes, max_bytes=2000)
    assert st["skipped"] == 1 and data.skipped == ["big.md"]


def test_huge_file_indexes_in_reasonable_time(tmp_path: Path) -> None:
    lines = [f"- item {i}: value {i * 7} for project p{i % 50}" for i in range(20000)]
    write(tmp_path, "huge.md", "# Huge\n\n" + "\n".join(lines) + "\n")
    t0 = time.perf_counter()
    mem = Memory(tmp_path)
    st = mem.index()
    assert st["chunks"] == 20000
    hits = mem.search("item 12345", now=NOW, refresh=False).hits
    assert hits[0].chunk.start_line == 12345 + 3
    assert time.perf_counter() - t0 < 60


def test_unicode_paths_and_content(tmp_path: Path) -> None:
    write(tmp_path, "café/notes ü.md", "# Café\n\n- Barista: Zoë Ünal\n- 東京 trip in May\n")
    mem = Memory(tmp_path)
    hits = mem.search("zoe unal", now=NOW).hits
    assert hits[0].chunk.path == "café/notes ü.md"
    assert mem.search("東京", now=NOW).hits


def test_invalid_utf8_in_notes_is_replaced_not_fatal(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_bytes(b"caf\xe9 latte notes\n")
    assert Memory(tmp_path).search("latte", now=NOW).hits


def test_custom_index_dir(notes: Path, tmp_path: Path) -> None:
    mem = Memory(notes, index_dir=tmp_path / "elsewhere")
    mem.index()
    assert (tmp_path / "elsewhere" / "index.json").exists()
    assert not (notes / ".plainmem").exists()


def test_save_is_atomic_and_leaves_no_temp_files(notes: Path) -> None:
    mem = Memory(notes)
    mem.index()
    mem.index()
    leftovers = [p.name for p in mem.index_file.parent.iterdir() if p.name != "index.json"]
    assert leftovers == []


def test_stats(notes: Path) -> None:
    st = Memory(notes).stats(now=NOW)
    assert st["files"] == 3 and st["conflicts"] == 1 and st["must_reverify"] == 1 and st["index_bytes"] > 0
