"""Streamlit UI: scrape aesthetic clinic leads + a built-in CRM.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st

from clinic_scraper import config, crm
from clinic_scraper.models import LEAD_FIELDS
from clinic_scraper.niche import NICHE_KEYWORDS
from clinic_scraper.pipeline import run
from clinic_scraper.sample import sample_leads

st.set_page_config(page_title="Clinic Lead Scraper + CRM", page_icon="✨", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 2.2rem;}
      h1 {font-weight: 800; letter-spacing: -0.02em;}
      [data-testid="stMetric"] {background: #f7f7fb; border-radius: 12px;
        padding: 0.75rem 1rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("✨ Clinic Lead Scraper + CRM")
st.caption(
    "Find aesthetic clinics with email + socials, score them for your AI DM "
    "service, and work them through a pipeline."
)

scrape_tab, crm_tab = st.tabs(["🔎 Scrape", "📇 CRM"])


# --------------------------------------------------------------------------- #
# Scrape tab
# --------------------------------------------------------------------------- #
with scrape_tab:
    with st.sidebar:
        st.header("Search")
        term = st.text_input("Search term", value="aesthetic clinic")
        cities_raw = st.text_area(
            "Cities (one per line)",
            value="Austin TX\nMiami FL\nDallas TX",
            help="Each city becomes its own search. Blank = search the term as-is.",
        )
        max_results = st.slider("Max results per city", 10, 60, 40, step=10)
        st.divider()
        st.subheader("Filters")
        chosen_niches = st.multiselect(
            "Niches (empty = all aesthetic targets)",
            options=list(NICHE_KEYWORDS.keys()),
        )
        min_score = st.slider("Minimum DM-ready score", 0, 100, 0, step=5)
        enrich = st.toggle(
            "Enrich from website (email + socials)",
            value=True,
            help="Visits each clinic's site. Slower, but finds emails & Instagram.",
        )
        go = st.button("🔎 Scrape leads", type="primary", use_container_width=True)
        demo = st.button("🧪 Load demo data", use_container_width=True)

    if demo:
        leads = sample_leads()
        st.session_state["leads"] = leads
        st.session_state["df"] = pd.DataFrame(
            [lead.as_row() for lead in leads], columns=LEAD_FIELDS
        )

    if not config.GOOGLE_PLACES_API_KEY:
        st.info(
            "No `GOOGLE_PLACES_API_KEY` set yet — add it to a `.env` file "
            "(see `.env.example`) to scrape live. Meanwhile, hit "
            "**🧪 Load demo data** to explore the UI."
        )

    if go:
        cities = [c.strip() for c in cities_raw.splitlines() if c.strip()]
        queries = [f"{term} in {city}" for city in cities] if cities else [term]
        status = st.empty()

        try:
            with st.spinner("Working…"):
                leads = run(
                    queries,
                    max_results_per_query=max_results,
                    enrich=enrich,
                    niches=chosen_niches or None,
                    min_score=min_score,
                    progress=lambda msg: status.write(f"`{msg}`"),
                )
        except RuntimeError as exc:
            st.error(str(exc))
            st.stop()

        if not leads:
            st.info("No clinics matched your search and filters.")
        else:
            st.session_state["leads"] = leads
            st.session_state["df"] = pd.DataFrame(
                [lead.as_row() for lead in leads], columns=LEAD_FIELDS
            )

    if "df" in st.session_state:
        df = st.session_state["df"]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Clinics", len(df))
        c2.metric("With email", int((df["email"] != "").sum()))
        c3.metric("With Instagram", int((df["instagram"] != "").sum()))
        c4.metric("Hot (score ≥ 60)", int((df["dm_score"] >= 60).sum()))

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "dm_score": st.column_config.ProgressColumn(
                    "DM score", min_value=0, max_value=100, format="%d"
                ),
                "website": st.column_config.LinkColumn("website"),
                "instagram": st.column_config.LinkColumn("instagram"),
                "facebook": st.column_config.LinkColumn("facebook"),
                "google_maps_url": st.column_config.LinkColumn("google_maps_url"),
            },
        )

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        xlsx_buf = io.BytesIO()
        with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Leads")
        xlsx_buf.seek(0)

        d1, d2, d3 = st.columns(3)
        d1.download_button(
            "⬇️ CSV",
            df.to_csv(index=False).encode("utf-8"),
            file_name=f"clinic_leads_{stamp}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        d2.download_button(
            "⬇️ Excel",
            xlsx_buf,
            file_name=f"clinic_leads_{stamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        if d3.button("📇 Push to CRM", type="primary", use_container_width=True):
            result = crm.upsert_leads(st.session_state["leads"])
            st.success(
                f"Pushed to CRM — {result['inserted']} new, "
                f"{result['updated']} refreshed."
            )


# --------------------------------------------------------------------------- #
# CRM tab
# --------------------------------------------------------------------------- #
with crm_tab:
    crm.init_db()
    s = crm.stats()

    if s["total"] == 0:
        st.info("CRM is empty. Scrape some leads and hit **Push to CRM**.")
    else:
        cols = st.columns(len(crm.STATUSES) + 1)
        cols[0].metric("Total", s["total"])
        for i, status in enumerate(crm.STATUSES, start=1):
            cols[i].metric(status.title(), s["by_status"].get(status, 0))

        f1, f2, f3 = st.columns(3)
        flt_status = f1.selectbox("Status", ["(all)"] + crm.STATUSES)
        flt_niche = f2.selectbox(
            "Niche", ["(all)"] + list(NICHE_KEYWORDS.keys())
        )
        flt_score = f3.slider("Min DM score", 0, 100, 0, step=5)

        rows = crm.list_leads(
            status=None if flt_status == "(all)" else flt_status,
            niche=None if flt_niche == "(all)" else flt_niche,
            min_score=flt_score,
        )

        if not rows:
            st.info("No leads match these filters.")
        else:
            crm_df = pd.DataFrame(rows)
            # Columns you edit live up front; keep the rest read-only.
            view_cols = [
                "name", "dm_score", "niche", "status", "notes", "phone",
                "email", "instagram", "website", "rating", "reviews",
                "address", "dedup_key",
            ]
            editor_df = crm_df[view_cols].copy()

            edited = st.data_editor(
                editor_df,
                use_container_width=True,
                hide_index=True,
                disabled=[c for c in view_cols if c not in ("status", "notes")],
                column_config={
                    "dm_score": st.column_config.ProgressColumn(
                        "DM score", min_value=0, max_value=100, format="%d"
                    ),
                    "status": st.column_config.SelectboxColumn(
                        "status", options=crm.STATUSES, required=True
                    ),
                    "instagram": st.column_config.LinkColumn("instagram"),
                    "website": st.column_config.LinkColumn("website"),
                    "dedup_key": None,  # hidden, but used as the row key on save
                },
                key="crm_editor",
            )

            if st.button("💾 Save changes", type="primary"):
                changed = 0
                original = editor_df.set_index("dedup_key")
                for _, row in edited.iterrows():
                    key = row["dedup_key"]
                    if row["status"] != original.loc[key, "status"]:
                        crm.update_status(key, row["status"])
                        changed += 1
                    if row["notes"] != original.loc[key, "notes"]:
                        crm.update_notes(key, row["notes"] or "")
                        changed += 1
                st.success(f"Saved {changed} change(s).")
                st.rerun()
