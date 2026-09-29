import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "bench"
sys.path.insert(0, str(BENCH))

import run as bench_run  # noqa: E402
import synth  # noqa: E402

from plainmem import engine_from_texts  # noqa: E402


@pytest.fixture(scope="module")
def corpus():
    return synth.generate(7)


def test_generator_is_deterministic(corpus) -> None:
    again = synth.generate(7)
    assert corpus.texts() == again.texts()
    assert [q.query for q in corpus.queries] == [q.query for q in again.queries]
    assert synth.generate(8).texts() != corpus.texts()


def test_corpus_meets_size_targets(corpus) -> None:
    eng = engine_from_texts(corpus.texts(), corpus.mtimes())
    assert len(corpus.files) >= 300
    assert len(eng.chunks) >= 2000
    assert len(corpus.queries) >= 120
    assert {q.qtype for q in corpus.queries} == {"lookup", "paraphrase", "superseded", "stale"}


def test_every_label_points_at_a_real_line(corpus) -> None:
    texts = corpus.texts()
    for q in corpus.queries:
        lines = texts[q.path].split("\n")
        assert lines[q.line - 1].strip(), q
        if q.qtype == "superseded":
            assert texts[q.old_path].split("\n")[q.old_line - 1].strip(), q
        if q.qtype == "stale":
            assert q.expect_flag is not None


def test_stale_queries_include_fresh_controls(corpus) -> None:
    flags = [q.expect_flag for q in corpus.queries if q.qtype == "stale"]
    assert any(flags) and not all(flags)


def test_evaluate_metrics_on_toy_system() -> None:
    q1 = synth.Query("q1", "lookup", "x", "a.md", 3)
    q2 = synth.Query("q2", "superseded", "y", "new.md", 1, old_path="old.md", old_line=1)
    q3 = synth.Query("q3", "stale", "z", "s.md", 1, expect_flag=True)

    def system(query: str):
        R = bench_run.Ranked
        return {
            "x": [R("b.md", 1, 1, None), R("a.md", 2, 4, None)],
            "y": [R("old.md", 1, 1, None), R("new.md", 1, 1, None)],
            "z": [R("s.md", 1, 1, False)],
        }[query]

    m = bench_run.evaluate(system, [q1, q2, q3])
    assert m["by_type"]["lookup"] == {"r1": 0.0, "r5": 1.0, "mrr": 0.5}
    assert m["stale_answer_rate"] == 1.0
    assert m["false_fresh_rate"] == 1.0
    assert m["over_flag_rate"] is None
    assert m["overall"]["r5"] == 1.0
