import pytest

from plainmem.facts import extract
from plainmem.markdown import parse


def facts(text: str, path: str = "a.md"):
    doc = parse(path, text)
    return [a for c in doc.chunks for a in extract(c, doc)]


def test_key_value_line_qualified_with_title() -> None:
    [a] = facts("# Orion\n\n- Project lead: Dana Whit\n")
    assert a.key == "lead orion project" and a.value == "dana whit" and a.raw_value == "Dana Whit"


def test_log_entry_not_qualified() -> None:
    [a] = facts("# 2026-08-14\n\n- Orion project lead: Sam Okafor\n")
    assert a.key == "lead orion project"


def test_entity_front_matter_wins_over_title() -> None:
    [a] = facts("---\nentity: Atlas\n---\n# Some notes\n\n- Status: paused\n")
    assert a.key == "atla statu"


def test_same_generic_key_in_two_docs_differs() -> None:
    [a] = facts("# Orion\n\n- Status: active\n", "orion.md")
    [b] = facts("# Atlas\n\n- Status: paused\n", "atlas.md")
    assert a.key != b.key


@pytest.mark.parametrize(
    ("line", "value"),
    [
        ("The Orion project lead is now Sam Okafor.", "sam okafor"),
        ("Mara Quell's company is now Fernwood Bio.", "fernwood bio"),
        ("The office wifi changed to pinecone-42.", "pinecone 42"),
    ],
)
def test_is_now_sentences(line: str, value: str) -> None:
    got = facts(f"# 2026-01-01\n\n{line}\n")
    assert [a.value for a in got] == [value]


@pytest.mark.parametrize("line", ["It is raining.", "This is great.", "She is out today.", "There is a queue."])
def test_pronoun_subjects_are_ignored(line: str) -> None:
    assert facts(f"# 2026-01-01\n\n{line}\n") == []


def test_dates_urls_and_code_are_not_keys() -> None:
    assert facts("# 2026-01-01\n\n- 2026-01-02: decided things\n") == []
    assert facts("# 2026-01-01\n\n- https://example.com/path\n") == []
    assert facts("# T\n\n```\nkey: value\n```\n") == []


def test_value_drops_trailing_commentary_and_parentheses() -> None:
    [a] = facts("# 2026-01-01\n\n- Orion lead: Sam Okafor (took over from Dana), effective Monday\n")
    assert a.value == "sam okafor"


def test_long_keys_are_ignored() -> None:
    assert facts("# 2026-01-01\n\n- Wes Zell flagged a risk on Orion today: scope creep\n") == []


def test_inline_tags_do_not_leak_into_values() -> None:
    [a] = facts("# Gym\n\n- Hours: 6am-10pm [verified: 2026-01-01]\n")
    assert a.value == "6am 10pm"
