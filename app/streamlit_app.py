"""Streamlit demo: ask questions, map controls, browse sources.

    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.versions import status  # noqa: E402
from rag.answer import answer, status_note  # noqa: E402
from rag.llm import LLMError, UsageLimitError  # noqa: E402
from rag.mapper import map_control  # noqa: E402
from rag.retrieve import MODES, retrieve  # noqa: E402

st.set_page_config(page_title="AML Regulation Copilot", layout="wide")
st.title("AML Regulation Copilot")
st.caption("Answers grounded in Philippine AML/CTF regulations from the AMLC, BSP, SEC and Insurance "
           "Commission, using only the provisions in force on the chosen date. Every claim is cited and every "
           "citation is checked against the source. Research support, not legal advice.")

with st.sidebar:
    picked = st.date_input("Rules in force on", value=dt.date.today(), min_value=dt.date(2018, 1, 1),
                           max_value=dt.date.today(),
                           help="Superseded provisions are left out; earlier dates use the wording in force then.")
    AS_OF = picked.isoformat()
    st.caption("Transitional provisions (repealed but still in force during a phase-in) are labelled, "
               "and shown with the issuance replacing them.")

BADGE = {"current": "🟢", "transitional": "🟠", "superseded": "⚪"}

EXAMPLES = [
    "When must an STR be filed, and what counts as the occurrence date?",
    "What is the determination period for TMS-generated alerts?",
    "What must an insurer do before paying out a life policy to a high-risk PEP beneficiary?",
    "What automated functions must an electronic AML monitoring system have?",
]
CONTROL_EXAMPLE = ("Monthly, the compliance team runs the transaction monitoring system over the previous "
                   "month's transactions. Alerts are reviewed by an analyst and escalated to the Compliance "
                   "Officer, who decides whether to file an STR. Decisions not to file are recorded in the "
                   "case tool.")
STATUS_STYLE = {"gap": ("Gap", "🔴"), "partial": ("Partial", "🟠"), "covered": ("Covered", "🟢"),
                "not_applicable": ("Not applicable", "⚪")}


def show_sources(chunks, cited: set[int]) -> None:
    for i, c in enumerate(chunks, start=1):
        label = f"[{i}] {BADGE[status(c, AS_OF)]} {c.label}  ·  p. {c.page_start}"
        with st.expander(("● " if i in cited else "○ ") + label):
            st.caption(status_note(c, AS_OF))
            st.write(c.text)


ask_tab, map_tab, search_tab = st.tabs(["Ask", "Map a control", "Search sources"])

with ask_tab:
    pick = st.selectbox("Example questions", ["—"] + EXAMPLES)
    question = st.text_input("Question", value="" if pick == "—" else pick)
    if st.button("Answer", type="primary", disabled=not question):
        with st.spinner("Retrieving provisions and drafting a cited answer…"):
            try:
                res = answer(question, as_of=None if AS_OF == dt.date.today().isoformat() else AS_OF)
            except UsageLimitError:
                st.error("The LLM usage limit is reached. Try again when it resets.")
                st.stop()
            except LLMError as e:
                st.error(f"LLM call failed: {e}")
                st.stop()
        st.markdown(res.text)
        r = res.report
        if r.refused:
            st.info("The sources don't answer this, so the copilot declined rather than guess.")
        elif r.ok:
            st.success(f"Citations verified: {len(r.cited)} sources cited, all quotes found in the cited text.")
        else:
            st.warning(f"Citation check flagged issues: invalid {r.invalid_citations}, "
                       f"unsupported quotes {r.unsupported_quotes}, uncited sentences {len(r.uncited_sentences)}.")
        st.subheader("Sources")
        show_sources(res.sources, set(r.cited))

with map_tab:
    control = st.text_area("Describe an internal control or test case", value=CONTROL_EXAMPLE, height=140)
    show_na = st.checkbox("Show unrelated provisions")
    if st.button("Map to regulation", type="primary", disabled=not control.strip()):
        with st.spinner("Finding the provisions this control should satisfy…"):
            try:
                res = map_control(control, as_of=AS_OF)
            except LLMError as e:
                st.error(f"LLM call failed: {e}")
                st.stop()
        counts = {s: len(res.by_status(s)) for s in STATUS_STYLE}
        cols = st.columns(4)
        for col, (s, (label, icon)) in zip(cols, STATUS_STYLE.items()):
            col.metric(f"{icon} {label}", counts[s])
        for a in res.assessments:
            if a.status == "not_applicable" and not show_na:
                continue
            label, icon = STATUS_STYLE[a.status]
            with st.container(border=True):
                st.markdown(f"**{icon} {label}** · {a.provision.label}")
                st.markdown(f"> {a.requirement_quote}")
                if not a.quote_verified:
                    st.caption("⚠ This quote could not be matched to the provision text.")
                st.write(a.reason)
                if a.recommendation:
                    st.markdown(f"**Recommendation:** {a.recommendation}")

with search_tab:
    q = st.text_input("Search the corpus (no LLM)")
    mode = st.radio("Retrieval", MODES, index=len(MODES) - 1, horizontal=True)
    if q:
        show_sources(retrieve(q, k=8, mode=mode, as_of=AS_OF), set())
