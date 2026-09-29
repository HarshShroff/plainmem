import multiprocessing as mp
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from plainmem import log
from plainmem.log import LOCK_NAME, LockTimeout, append, rotate, split_sections


def test_append_creates_log_and_heading(tmp_path: Path) -> None:
    p = append(tmp_path, "first entry", when=date(2026, 3, 1))
    assert p.read_text() == "# Log\n\n## 2026-03-01\n\n- first entry\n"


def test_same_day_appends_under_one_heading(tmp_path: Path) -> None:
    append(tmp_path, "a", when=date(2026, 3, 1))
    append(tmp_path, "b", when=date(2026, 3, 1))
    text = (tmp_path / "log.md").read_text()
    assert text.count("## 2026-03-01") == 1 and text.endswith("- a\n- b\n")


def test_new_day_new_heading(tmp_path: Path) -> None:
    append(tmp_path, "a", when=date(2026, 3, 1))
    append(tmp_path, "b", when=date(2026, 3, 2))
    _, secs = split_sections((tmp_path / "log.md").read_text())
    assert [s.day for s in secs] == [date(2026, 3, 1), date(2026, 3, 2)]


def test_multiline_entry_is_indented(tmp_path: Path) -> None:
    append(tmp_path, "line one\nline two\n\nline four", when=date(2026, 3, 1))
    assert (tmp_path / "log.md").read_text().endswith("- line one\n  line two\n\n  line four\n")


def test_empty_entry_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        append(tmp_path, "   ")


def test_aware_datetime_is_filed_under_utc_date(tmp_path: Path) -> None:
    ny = timezone(timedelta(hours=-5))
    append(tmp_path, "late", when=datetime(2026, 3, 1, 23, 30, tzinfo=ny))
    assert "## 2026-03-02" in (tmp_path / "log.md").read_text()


def test_naive_datetime_is_treated_as_utc(tmp_path: Path) -> None:
    append(tmp_path, "x", when=datetime(2026, 3, 1, 23, 30))
    assert "## 2026-03-01" in (tmp_path / "log.md").read_text()


def test_append_to_file_without_trailing_newline(tmp_path: Path) -> None:
    (tmp_path / "log.md").write_text("# Log\n\n## 2026-03-01\n\n- a")
    append(tmp_path, "b", when=date(2026, 3, 1))
    assert (tmp_path / "log.md").read_text().endswith("- a\n- b\n")


def test_lock_is_exclusive_and_released(tmp_path: Path) -> None:
    with log.lock(tmp_path):
        assert (tmp_path / LOCK_NAME).is_dir()
        with pytest.raises(LockTimeout), log.lock(tmp_path, timeout=0.1):
            pass
    assert not (tmp_path / LOCK_NAME).exists()


def test_lock_released_on_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), log.lock(tmp_path):
        raise RuntimeError("boom")
    assert not (tmp_path / LOCK_NAME).exists()


def test_stale_lock_is_broken(tmp_path: Path) -> None:
    lockdir = tmp_path / LOCK_NAME
    lockdir.mkdir()
    old = time.time() - 3600
    os.utime(lockdir, (old, old))
    with log.lock(tmp_path, timeout=1, stale_after=60):
        pass


def test_live_lock_blocks_append(tmp_path: Path) -> None:
    (tmp_path / LOCK_NAME).mkdir()
    with pytest.raises(LockTimeout):
        append(tmp_path, "x", timeout=0.2)


def _writer(root: str, wid: int, n: int) -> None:
    for i in range(n):
        append(Path(root), f"writer {wid} entry {i}", when=date(2026, 3, 1 + (i % 3)), timeout=30)


def test_concurrent_writers_lose_nothing(tmp_path: Path) -> None:
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_writer, args=(str(tmp_path), w, 25)) for w in range(6)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    text = (tmp_path / "log.md").read_text()
    for w in range(6):
        for i in range(25):
            assert text.count(f"- writer {w} entry {i}\n") == 1
    assert not (tmp_path / LOCK_NAME).exists()


def _log_with(tmp_path: Path, days: list[date]) -> str:
    for d in days:
        append(tmp_path, f"entry for {d}", when=d)
        append(tmp_path, f"second for {d}\nwith detail", when=d)
    return (tmp_path / "log.md").read_text()


def test_rotate_moves_old_sections_verbatim(tmp_path: Path) -> None:
    days = [date(2026, 7, 30), date(2026, 8, 2), date(2026, 9, 20), date(2026, 9, 28)]
    original = _log_with(tmp_path, days)
    out = rotate(tmp_path, keep_days=14, now=date(2026, 9, 29))
    assert out["archived"] == 2 and out["kept"] == 2
    assert out["files"] == ["archive/log-2026-07.md", "archive/log-2026-08.md"]
    remaining = (tmp_path / "log.md").read_text()
    archived = "".join((tmp_path / f).read_text() for f in out["files"])
    _, orig_secs = split_sections(original)
    for s in orig_secs:
        assert (s.text in remaining) != (s.text.strip() in archived)
    assert remaining.startswith("# Log")


def test_rotate_is_idempotent_and_crash_safe(tmp_path: Path) -> None:
    _log_with(tmp_path, [date(2026, 7, 30), date(2026, 9, 28)])
    original = (tmp_path / "log.md").read_text()
    rotate(tmp_path, keep_days=14, now=date(2026, 9, 29))
    archive = (tmp_path / "archive/log-2026-07.md").read_text()
    # simulate a crash after the archive write but before the log rewrite
    (tmp_path / "log.md").write_text(original)
    rotate(tmp_path, keep_days=14, now=date(2026, 9, 29))
    assert (tmp_path / "archive/log-2026-07.md").read_text() == archive
    assert rotate(tmp_path, keep_days=14, now=date(2026, 9, 29))["archived"] == 0


def test_rotate_without_log_or_old_entries(tmp_path: Path) -> None:
    assert rotate(tmp_path, 14)["archived"] == 0
    _log_with(tmp_path, [date(2026, 9, 28)])
    assert rotate(tmp_path, 14, now=date(2026, 9, 29)) == {"archived": 0, "kept": 1, "files": []}


def test_rotate_appends_to_existing_month_archive(tmp_path: Path) -> None:
    _log_with(tmp_path, [date(2026, 7, 1)])
    rotate(tmp_path, 14, now=date(2026, 9, 29))
    _log_with(tmp_path, [date(2026, 7, 20)])
    rotate(tmp_path, 14, now=date(2026, 9, 29))
    a = (tmp_path / "archive/log-2026-07.md").read_text()
    assert a.index("## 2026-07-01") < a.index("## 2026-07-20")
