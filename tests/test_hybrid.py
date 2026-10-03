from datetime import date
from pathlib import Path

import pytest

from plainmem import Memory, engine_from_texts, hybrid
from plainmem.cli import EXIT_USAGE, main
from plainmem.hybrid import Hybrid, rrf

from .conftest import NOW, write

# A toy embedding: one dimension per concept, so "heads" and "lead" land together.
CONCEPTS = [("lead", "heads", "runs", "charge"), ("region", "hosted", "datacenter"), ("orion",), ("atlas",)]


def stub_embed(texts: list[str]) -> list[list[float]]:
    out = []
    for t in texts:
        low = t.lower()
        out.append([float(sum(low.count(w) for w in group)) + 0.01 for group in CONCEPTS])
    return out


ORION = "---\nverified: 2025-11-02\n---\n# Orion\n\n- Project lead: Dana Whit\n- Deploy region: us-east-1\n"
LOG = "# Log\n\n## 2026-03-01\n\n- Orion project lead: Sam Okafor\n\n## 2026-07-01\n\n- Orion project lead: Kai Moss\n"


def test_rrf_sums_reciprocal_ranks() -> None:
    fused = rrf([[1, 2], [2, 3]], k=60)
    assert fused[2] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[1] == pytest.approx(1 / 61) and fused[3] == pytest.approx(1 / 62)
    assert max(fused, key=fused.get) == 2


def test_hybrid_finds_a_paraphrase_bm25_misses() -> None:
    eng = engine_from_texts({"orion.md": ORION, "log.md": LOG})
    q = "who heads it?"
    assert eng.search(q, now=NOW) == []  # no shared words at all
    hits = Hybrid(eng, stub_embed).search(q, k=3, now=NOW)
    assert hits and "Kai Moss" in hits[0].chunk.clean_text()  # newest version first, lifecycle still applies
    assert any(h.status == "SUPERSEDED" for h in hits)


def test_hybrid_respects_as_of() -> None:
    eng = engine_from_texts({"orion.md": ORION, "log.md": LOG})
    hits = Hybrid(eng, stub_embed).search("Orion project lead", k=5, now=NOW, as_of=date(2026, 4, 1))
    texts = [h.chunk.clean_text() for h in hits]
    assert texts[0].endswith("Sam Okafor") and not any("Kai" in t for t in texts)


def test_memory_hybrid_mode_and_explain(tmp_path: Path) -> None:
    root = tmp_path / "n"
    write(root, "orion.md", ORION, when=date(2026, 9, 1))
    write(root, "log.md", LOG, when=date(2026, 9, 1))
    mem = Memory(root, embed=stub_embed)
    assert mem.search("who heads it", now=NOW, mode="hybrid").to_dict()["results"]
    r = mem.explain("Who is in charge of Orion?", now=NOW, mode="hybrid")
    assert r["fact"]["current"]["value"] == "Kai Moss"
    r = mem.explain("Who is in charge of Orion?", now=NOW, mode="hybrid", as_of=date(2026, 4, 1))
    assert r["fact"]["current"]["value"] == "Sam Okafor"


def test_cli_hybrid_without_extra_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "n", "orion.md", ORION)

    def missing(model: str = "") -> None:
        raise ImportError("hybrid retrieval needs the embeddings extra: pip install 'plainmem[embeddings]'")

    monkeypatch.setattr(hybrid, "sentence_transformer", missing)
    assert main(["--root", str(tmp_path / "n"), "search", "orion", "--mode", "hybrid"]) == EXIT_USAGE
    assert "embeddings extra" in capsys.readouterr().err


def test_core_does_not_import_hybrid() -> None:
    import subprocess
    import sys

    code = "import sys, plainmem, plainmem.cli, plainmem.memory; print('plainmem.hybrid' in sys.modules)"
    src = str(Path(__file__).resolve().parent.parent / "src")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={"PYTHONPATH": src})
    assert out.stdout.strip() == "False"
