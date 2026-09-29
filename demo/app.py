"""plainmem live demo. Run: streamlit run demo/app.py

Everything runs in this process on a synthetic corpus. No LLM, no API key, no
network calls. Notes a visitor adds live only in their browser session.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from logic import (  # noqa: E402
    NOW,
    build_engine,
    load_base,
    make_note,
    row_html,
    run_query,
    sample_queries,
    visitor_conflicts,
)

ROOT = Path(__file__).resolve().parent.parent

st.set_page_config(page_title="plainmem demo", layout="wide")


@st.cache_resource
def base():
    texts, mtimes, queries = load_base()
    return texts, mtimes, queries, build_engine(texts, mtimes, {})


texts, mtimes, queries, base_engine = base()
notes: dict[str, str] = st.session_state.setdefault("visitor_notes", {})
engine = build_engine(texts, mtimes, notes) if notes else base_engine

st.title("plainmem")
st.caption(
    f"Markdown-first memory with freshness awareness. Synthetic corpus: {len(texts)} notes, "
    f"{len(engine.chunks)} chunks. Pretend today is {NOW}. Nothing leaves this page."
)

examples = sample_queries(queries)
col_q, col_ex = st.columns([3, 2])
with col_ex:
    pick = st.selectbox("Example questions", ["(type your own)", *examples])
with col_q:
    default = "" if pick == "(type your own)" else pick
    query = st.text_input("Ask the notes", value=default or examples[0], max_chars=200)

left, right = st.columns(2)
with left:
    st.subheader("Plain BM25")
    st.caption("Stemmed BM25. No notion of time.")
    for r in run_query(engine, query, "bm25"):
        st.markdown(row_html(r), unsafe_allow_html=True)
with right:
    st.subheader("plainmem full ranker")
    st.caption("BM25 + time decay + supersession, with freshness badges.")
    rows = run_query(engine, query, "full")
    if not rows:
        st.info("no_match: true. The search ran and found nothing, which is different from not searching.")
    for r in rows:
        st.markdown(row_html(r), unsafe_allow_html=True)

st.divider()
st.subheader("Add a note and watch supersession")
st.caption(
    "Write a newer fact that contradicts an old one, e.g. `Orion project lead: Your Name` or "
    "`The Orion designer is now Your Name.` Then search for it above. Stored in this session only."
)
with st.form("add", clear_on_submit=True):
    text = st.text_input("Note", max_chars=400, placeholder="Orion project lead: Your Name")
    day = st.date_input("Dated", value=NOW, min_value=NOW - timedelta(days=900), max_value=NOW)
    if st.form_submit_button("Add note"):
        try:
            path, md = make_note(text, day, len(notes))
            notes[path] = md
            st.rerun()
        except ValueError as e:
            st.warning(str(e))

if notes:
    for path, md in notes.items():
        st.code(f"{path}\n{md}", language="markdown")
    conflicts = visitor_conflicts(engine)
    if conflicts:
        st.markdown("**Conflicts your notes created or resolved**")
        st.table(conflicts)
    else:
        st.caption("Your notes do not conflict with anything yet. Use the `key: value` or `X is now Y` shape.")
    if st.button("Clear my notes"):
        notes.clear()
        st.rerun()

st.divider()
st.subheader("Benchmark")
results = ROOT / "bench" / "results.md"
if results.exists():
    st.markdown(results.read_text())
    st.caption("Author-written synthetic corpus and labels. Not an independent benchmark.")
else:
    st.caption("Run `python bench/run.py` to produce the table.")
