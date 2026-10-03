import copy
import json
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "bench"
sys.path.insert(0, str(BENCH))

from supersession import generate as sg  # noqa: E402


@pytest.fixture(scope="module")
def run2():
    return sg.generate(300, 4127, "t")


def test_templates_have_no_key_collisions() -> None:
    assert sg.audit_templates() == []


def test_audit_flags_the_run1_backup_template() -> None:
    t = copy.deepcopy(sg.T)
    t["deploy region"]["E"][2] = "{E} keeps backups in {new}."
    assert sg.audit_templates(t) == ["deploy region/E: '{E} keeps backups in {new}.' touches 'backup region'"]


def test_audit_flags_a_positive_that_names_a_sibling() -> None:
    t = copy.deepcopy(sg.T)
    t["CI provider"]["C"][0] = "{E} CD runs on {new} now."
    assert any("touches 'CD provider'" in p for p in sg.audit_templates(t))


def test_touches_needs_cue_words_and_kind() -> None:
    assert sg.touches("Acme keeps backups in us-west-2.", "Backup region", "region")
    assert not sg.touches("Acme keeps backups in us-west-2.", "Backup region", "person")
    assert not sg.touches("Acme added a read replica in us-west-2.", "Replica database", "region")
    assert not sg.touches("Acme hosts its status page in us-west-2.", "Backup region", "region")


def test_generation_fails_on_a_collision(monkeypatch) -> None:
    t = copy.deepcopy(sg.T)
    t["deploy region"]["E"][2] = "{E} keeps backups in {new}."
    monkeypatch.setattr(sg, "T", t)
    with pytest.raises(ValueError, match="key collision"):
        sg.generate(300, 2026)


def test_check_cases_on_run1_data_finds_the_mislabelled_note(monkeypatch) -> None:
    t = copy.deepcopy(sg.T)
    t["deploy region"]["E"][2] = "{E} keeps backups in {new}."
    monkeypatch.setattr(sg, "T", t)
    monkeypatch.setattr(sg, "audit_templates", lambda templates=None: [])
    with pytest.raises(ValueError, match="BasaltStack keeps backups in us-west-2"):
        sg.generate(300, 2026)


def test_run2_ids_and_split_are_disjoint_from_run1(run2) -> None:
    _, cases, _ = run2
    here = BENCH / "supersession"
    v2 = json.loads((here / "split_v2.json").read_text())
    v1 = json.loads((here / "run1" / "split.json").read_text())
    assert v2["cases_sha256"] == sg.cases_sha(cases)
    assert sorted(c.id for c in cases if c.split == "heldout") == v2["heldout"]
    assert not set(v2["heldout"]) & set(v1["heldout"])
    assert v2["seed"] != v1["seed"]


def test_run2_negatives_never_touch_an_existing_key(run2) -> None:
    files, cases, _ = run2
    assert sg.check_cases(files, cases) == []
    assert not any("keeps backups" in c.note for c in cases)
