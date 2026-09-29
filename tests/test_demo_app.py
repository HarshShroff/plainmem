from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "demo" / "app.py")


def test_app_renders_without_exceptions() -> None:
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.title[0].value == "plainmem"
    assert len(at.subheader) >= 3


def test_app_add_note_creates_supersession() -> None:
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input[1].input("Obsidian project lead: Visitor Person")
    at.button[0].click().run()
    assert not at.exception
    assert "visitor/note-01.md" in at.session_state["visitor_notes"]
    at.text_input[0].input("who is the Obsidian project lead").run()
    html = " ".join(m.value for m in at.markdown)
    assert "visitor/note-01.md:3" in html and "SUPERSEDED" in html
