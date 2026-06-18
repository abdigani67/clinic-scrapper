"""Streamlit UI for the aesthetic clinic lead scraper.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st

from clinic_scraper import config, export
from clinic_scraper.models import LEAD_FIELDS
from clinic_scraper.pipeline import run

st.set_page_config(page_title="Clinic Lead Scraper", page_icon="✨", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 2.5rem;}
      h1 {font-weight: 800; letter-spacing: -0.02em;}
      .stMetric {background: #f7f7fb; border-radius: 12px; padding: 0.75rem 1rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("✨ Aesthetic Clinic Lead Scraper")
st.caption(
    "Find aesthetic clinics, med spas and cosmetic practices — with email and "
    "socials — to pitch your AI receptionist."
)

with st.sidebar:
    st.header("Search")
    term = st.text_input("Search term", value="aesthetic clinic")
    cities_raw = st.text_area(
        "Cities (one per line)",
        value="Austin TX\nMiami FL\nDallas TX",
        help="Each city becomes its own search. Leave blank to search the term as-is.",
    )
    max_results = st.slider("Max results per city", 10, 60, 40, step=10)
    enrich = st.toggle(
        "Enrich from website (email + socials)",
        value=True,
        help="Visits each clinic's site. Slower, but finds emails and Instagram.",
    )
    go = st.button("🔎 Scrape leads", type="primary", use_container_width=True)

if not config.GOOGLE_PLACES_API_KEY:
    st.warning(
        "No `GOOGLE_PLACES_API_KEY` found. Add it to a `.env` file "
        "(see `.env.example`) before scraping."
    )

if go:
    cities = [c.strip() for c in cities_raw.splitlines() if c.strip()]
    queries = [f"{term} in {city}" for city in cities] if cities else [term]

    status = st.empty()
    progress_bar = st.progress(0.0)

    # Rough progress: searches first, then one tick per enriched lead.
    def progress(msg: str) -> None:
        status.write(f"`{msg}`")

    try:
        with st.spinner("Working…"):
            leads = run(
                queries,
                max_results_per_query=max_results,
                enrich=enrich,
                progress=progress,
            )
        progress_bar.progress(1.0)
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    if not leads:
        st.info("No clinics found for that search.")
        st.stop()

    df = pd.DataFrame([lead.as_row() for lead in leads], columns=LEAD_FIELDS)
    st.session_state["df"] = df

if "df" in st.session_state:
    df = st.session_state["df"]

    total = len(df)
    with_email = int((df["email"] != "").sum())
    with_ig = int((df["instagram"] != "").sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Clinics", total)
    c2.metric("With email", with_email)
    c3.metric("With Instagram", with_ig)

    f1, f2 = st.columns(2)
    only_email = f1.checkbox("Only show leads with an email", value=False)
    only_ig = f2.checkbox("Only show leads with Instagram", value=False)

    view = df.copy()
    if only_email:
        view = view[view["email"] != ""]
    if only_ig:
        view = view[view["instagram"] != ""]

    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "website": st.column_config.LinkColumn("website"),
            "instagram": st.column_config.LinkColumn("instagram"),
            "facebook": st.column_config.LinkColumn("facebook"),
            "google_maps_url": st.column_config.LinkColumn("google_maps_url"),
        },
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_bytes = view.to_csv(index=False).encode("utf-8")

    xlsx_buf = io.BytesIO()
    # Reuse the styled Excel exporter via a temporary list of Leads-equivalent rows.
    with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
        view.to_excel(writer, index=False, sheet_name="Leads")
    xlsx_buf.seek(0)

    d1, d2 = st.columns(2)
    d1.download_button(
        "⬇️ Download CSV",
        csv_bytes,
        file_name=f"clinic_leads_{stamp}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    d2.download_button(
        "⬇️ Download Excel",
        xlsx_buf,
        file_name=f"clinic_leads_{stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
