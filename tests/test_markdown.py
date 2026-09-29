from datetime import date

import pytest

from plainmem.markdown import is_date_heading, parse, parse_date, split_front_matter


def test_front_matter_parsed_and_skipped() -> None:
    doc = parse("a.md", "---\nverified: 2026-01-02\nTitle: 'Hello'\n---\n# H\n\nBody\n")
    assert doc.meta == {"verified": "2026-01-02", "title": "Hello"}
    assert [c.text for c in doc.chunks] == ["Body"]
    assert doc.chunks[0].start_line == 7


def test_unterminated_front_matter_is_plain_text() -> None:
    meta, skip = split_front_matter(["---", "a: b", "no end"])
    assert (meta, skip) == ({}, 0)


def test_heading_path_nests_and_pops() -> None:
    doc = parse("a.md", "# A\n## B\n### C\ntext c\n## D\ntext d\n")
    assert [c.heading_path for c in doc.chunks] == [["A", "B", "C"], ["A", "D"]]
    assert doc.title == "A"


def test_list_items_are_separate_chunks_with_line_numbers() -> None:
    doc = parse("a.md", "# T\n\n- one\n- two\n  continued\n- three\n")
    assert [(c.start_line, c.end_line, c.kind) for c in doc.chunks] == [(3, 3, "item"), (4, 5, "item"), (6, 6, "item")]
    assert doc.chunks[1].text == "- two\n  continued"
    assert doc.chunks[0].cite == "a.md:3"


def test_numbered_list_items() -> None:
    doc = parse("a.md", "1. first\n2) second\n")
    assert len(doc.chunks) == 2


def test_paragraph_spans_lines_until_blank() -> None:
    doc = parse("a.md", "line one\nline two\n\nnext para\n")
    assert [c.text for c in doc.chunks] == ["line one\nline two", "next para"]


def test_code_fence_is_one_chunk_and_hides_headings() -> None:
    doc = parse("a.md", "# T\n\n```\n# not a heading\n\nstill code\n```\nafter\n")
    assert doc.chunks[0].kind == "code"
    assert "# not a heading" in doc.chunks[0].text
    assert doc.chunks[1].heading_path == ["T"]


def test_unclosed_fence_is_flushed_at_eof() -> None:
    doc = parse("a.md", "```\ncode forever\n")
    assert len(doc.chunks) == 1 and doc.chunks[0].kind == "code"


def test_table_rows_become_chunks_and_separator_is_dropped() -> None:
    doc = parse("a.md", "| k | v |\n|---|---|\n| a | 1 |\n")
    assert [c.text for c in doc.chunks] == ["| k | v |", "| a | 1 |"]


def test_inline_tags() -> None:
    doc = parse("a.md", "- Price $5 [verified: 2026-04-01] [volatile]\n")
    c = doc.chunks[0]
    assert c.verified == date(2026, 4, 1) and c.date_source == "inline" and c.volatile
    assert c.clean_text() == "- Price $5"


def test_dated_heading_dates_its_entries() -> None:
    doc = parse("log.md", "# Log\n\n## 2026-03-14\n\n- did a thing\n\n## 2026-03-15 Sun\n\n- another\n")
    assert [c.verified for c in doc.chunks] == [date(2026, 3, 14), date(2026, 3, 15)]
    assert all(c.date_source == "heading" for c in doc.chunks)


def test_inline_tag_beats_heading_date() -> None:
    doc = parse("log.md", "## 2026-03-14\n\n- fact [verified: 2026-05-01]\n")
    assert doc.chunks[0].verified == date(2026, 5, 1)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-03-14", date(2026, 3, 14)),
        ("on 2026-02-30 then 2026-03-01", date(2026, 3, 1)),
        ("no date", None),
        ("20260314", None),
        ("", None),
    ],
)
def test_parse_date(text: str, expected: date | None) -> None:
    assert parse_date(text) == expected


@pytest.mark.parametrize(
    ("heading", "expected"),
    [("2026-03-14", True), ("2026-03-14 Tue", True), ("Planning notes 2026-03-14 offsite", False), ("Orion", False)],
)
def test_is_date_heading(heading: str, expected: bool) -> None:
    assert is_date_heading(heading) is expected


def test_crlf_and_bom_are_normalised() -> None:
    doc = parse("a.md", "﻿# T\r\n\r\nbody\r\n")
    assert doc.chunks[0].text == "body" and doc.chunks[0].heading_path == ["T"]


def test_empty_and_heading_only_docs_have_no_chunks() -> None:
    assert parse("a.md", "").chunks == []
    assert parse("a.md", "# Only a heading\n").chunks == []
