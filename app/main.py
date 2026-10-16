"""Minimal Streamlit viewer; document-derived strings are rendered as text only."""
import streamlit as st

st.title("finTrance research report")
company = st.text_input("Company")
st.info("Run the CLI pipeline to generate an evidence-backed report.")
if company:
    st.write(f"Selected company: {company}")
