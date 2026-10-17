"""Evidence-only Streamlit dashboard for a stored or synthetic run."""
from html import escape

import pandas as pd
import plotly.express as px
import streamlit as st

from agent.orchestrator import Orchestrator
from agent.render.report import markdown
from store.dao import EvidenceStore


def report_json(report) -> str:
    return report.model_dump_json(indent=2)


def evidence_rows(report) -> list[dict[str, object]]:
    return [{"document": item.doc_id, "page": item.page, "quote": item.quote,
             "claim": item.claim} for item in report.evidence if item.doc_id and item.quote]


def metric_frame(store: EvidenceStore, ticker: str) -> pd.DataFrame:
    facts = store.facts_for(ticker)
    return pd.DataFrame([{"period": fact.period, "metric": fact.metric, "value": fact.value}
                         for fact in facts])


def run_dashboard(company: str, peers: list[str], log_placeholder):
    result = Orchestrator(callback=log_placeholder.write).run(company, peers=peers)
    return result.report, result.events


st.set_page_config(page_title="finTrance", layout="wide")
st.title("finTrance evidence dashboard")
company = st.text_input("Company or ticker")
peer_text = st.text_input("Optional peers (comma separated)")
run = st.button("Run deterministic pipeline", type="primary")

if run and company.strip():
    logs = st.empty()
    with st.status("Running evidence pipeline", expanded=True) as status:
        report, events = run_dashboard(
            company.strip(), [item.strip() for item in peer_text.split(",") if item.strip()], logs)
        status.update(label="Pipeline complete", state="complete")
    st.subheader("Discovery")
    st.markdown(escape(report.discovery))
    st.metric("Evidence strength", f"{report.evidence_strength.label} "
              f"({report.evidence_strength.total})")
    st.write(report.evidence_strength.points)

    frame = metric_frame(EvidenceStore(), company.strip())
    if not frame.empty:
        st.subheader("Metrics")
        st.plotly_chart(px.line(frame, x="period", y="value", color="metric",
                                markers=True), width="stretch")

    st.subheader("Why it matters")
    for item in report.why_it_matters:
        st.markdown(f"- {escape(item)}")
    st.subheader("Timeline")
    for item in report.timeline:
        st.write(item)
    st.subheader("Evidence")
    for item in evidence_rows(report):
        with st.expander(f"{item['document']} · page {item['page']}"):
            st.write(item["claim"])
            st.code(item["quote"])
    st.subheader("Counterargument")
    st.write(report.counterargument)
    st.subheader("Falsification condition")
    st.info(report.falsification_condition)
    st.subheader("How the agent got here")
    st.dataframe(pd.DataFrame(events), width="stretch")
    st.download_button("Download Markdown", markdown(report), file_name="report.md")
    st.download_button("Download JSON", report_json(report), file_name="report.json")
    st.download_button("Download HTML", f"<pre>{escape(markdown(report))}</pre>",
                       file_name="report.html", mime="text/html")
