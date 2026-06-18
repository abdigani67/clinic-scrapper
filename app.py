"""Streamlit UI: scrape aesthetic clinic leads + a built-in CRM.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st

from clinic_scraper import config, crm, runlog, ui
from clinic_scraper.models import LEAD_FIELDS
from clinic_scraper.niche import NICHE_KEYWORDS
from clinic_scraper.pipeline import run
from clinic_scraper.sample import sample_leads

st.set_page_config(
    page_title=f"{ui.APP_NAME} — {ui.APP_TAGLINE}",
    page_icon=ui.APP_ICON,
    layout="wide",
)

st.markdown(ui.CSS, unsafe_allow_html=True)
st.markdown(ui.hero_html(), unsafe_allow_html=True)

scrape_tab, crm_tab = st.tabs(["🔎 Scrape", "📇 CRM"])


# --------------------------------------------------------------------------- #
# Scrape tab
# --------------------------------------------------------------------------- #
with scrape_tab:
    with st.sidebar:
        st.header("Search")
        source_label = st.radio(
            "Data source",
            [
                "OpenStreetMap (free)",
                "Foursquare (free key)",
                "Google Places (needs API key)",
            ],
            help="OpenStreetMap needs no key. Foursquare needs a free key (no "
            "card). Google has ratings/reviews but needs a billing-enabled key.",
        )
        source = {
            "OpenStreetMap (free)": "osm",
            "Foursquare (free key)": "foursquare",
            "Google Places (needs API key)": "google",
        }[source_label]
        term = st.text_input("Search term", value="aesthetic clinic")
        cities_raw = st.text_area(
            "Cities (one per line)",
            value="Austin TX\nMiami FL\nDallas TX",
            help="Each city becomes its own search. Blank = search the term as-is.",
        )
        max_results = st.slider("Max results per city", 10, 120, 60, step=10)
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

    if source == "osm":
        st.info(
            "Using **OpenStreetMap** — free, no API key needed. Add one or more "
            "cities, then hit **Scrape leads**. (No star ratings from this source.)"
        )
    elif source == "foursquare" and not config.FOURSQUARE_API_KEY:
        st.info(
            "Foursquare needs a `FOURSQUARE_API_KEY` in your `.env` file. Get a "
            "free one (no card) at foursquare.com/developers, or switch to "
            "**OpenStreetMap (free)**."
        )
    elif source == "google" and not config.GOOGLE_PLACES_API_KEY:
        st.info(
            "Google Places needs a `GOOGLE_PLACES_API_KEY` in a `.env` file "
            "(see `.env.example`). No key yet? Switch the **Data source** above to "
            "**OpenStreetMap (free)**, or hit **🧪 Load demo data** to explore."
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
                    source=source,
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
        full_df = st.session_state["df"]

        # Live filters — applied to the already-scraped results so moving the
        # sliders updates the table instantly (no need to re-scrape).
        df = full_df[full_df["dm_score"] >= min_score]
        if chosen_niches:
            df = df[
                df["niche"].apply(
                    lambda n: any(sel in (n or "") for sel in chosen_niches)
                )
            ]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Showing", f"{len(df)} / {len(full_df)}")
        c2.metric("With email", int((df["email"] != "").sum()))
        c3.metric("With Instagram", int((df["instagram"] != "").sum()))
        c4.metric("Hot (score ≥ 60)", int((df["dm_score"] >= 60).sum()))

        if len(df) == 0:
            st.warning(
                "No leads match the current filters. Lower the **Minimum "
                "DM-ready score** or clear the **Niches** filter in the sidebar."
            )

        # Add a readable tier badge next to the numeric score.
        show_df = df.copy()
        show_df.insert(1, "tier", show_df["dm_score"].apply(ui.score_tier))

        # Show the essentials by default; the rest behind a toggle so the table
        # stays clean and uncluttered.
        show_all = st.toggle("Show all columns", value=False, key="scrape_all")
        essential = [
            "name", "tier", "dm_score", "niche",
            "phone", "email", "instagram_handle", "website",
        ]
        table_df = show_df if show_all else show_df[essential]

        st.dataframe(
            table_df,
            use_container_width=True,
            hide_index=True,
            height=560,
            column_config={
                "name": st.column_config.TextColumn("name", width="medium"),
                "tier": st.column_config.TextColumn("Tier"),
                "dm_score": st.column_config.ProgressColumn(
                    "DM score", min_value=0, max_value=100, format="%d"
                ),
                "instagram_handle": st.column_config.TextColumn("instagram handle"),
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

    # Run history — every scrape is logged so you can track results over time.
    history = runlog.read_log()
    if history:
        with st.expander(f"📈 Run history ({len(history)} runs logged)"):
            hist_df = pd.DataFrame(history)
            st.dataframe(hist_df, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ Download run history (CSV)",
                hist_df.to_csv(index=False).encode("utf-8"),
                file_name="scrape_log.csv",
                mime="text/csv",
            )


# --------------------------------------------------------------------------- #
# CRM tab
# --------------------------------------------------------------------------- #
STATUS_EMOJI = {
    "new": "⚪ New",
    "contacted": "📨 Contacted",
    "replied": "💬 Replied",
    "demo": "📅 Demo",
    "won": "🏆 Won",
    "lost": "❌ Lost",
}

with crm_tab:
    crm.init_db()
    s = crm.stats()

    st.subheader("Your pipeline")
    st.caption(
        "Edit the **Stage** and **Notes** columns right in the table, then click "
        "**Save changes**. Sort by DM score and work the 🟢 Hot leads first."
    )

    if s["total"] == 0:
        st.info(
            "Your CRM is empty. Go to the **Scrape** tab, find clinics, and hit "
            "**📇 Push to CRM** to start your pipeline."
        )
    else:
        cols = st.columns(len(crm.STATUSES) + 1)
        cols[0].metric("Total leads", s["total"])
        for i, status in enumerate(crm.STATUSES, start=1):
            cols[i].metric(
                STATUS_EMOJI[status], s["by_status"].get(status, 0)
            )

        st.markdown("")
        f1, f2, f3, f4 = st.columns([1.4, 1, 1, 1])
        flt_name = f1.text_input("🔎 Search by name", placeholder="e.g. Quinn")
        flt_status = f2.selectbox("Stage", ["(all)"] + crm.STATUSES)
        flt_niche = f3.selectbox("Niche", ["(all)"] + list(NICHE_KEYWORDS.keys()))
        flt_score = f4.slider("Min DM score", 0, 100, 0, step=5)

        rows = crm.list_leads(
            status=None if flt_status == "(all)" else flt_status,
            niche=None if flt_niche == "(all)" else flt_niche,
            min_score=flt_score,
        )
        if flt_name:
            needle = flt_name.lower()
            rows = [r for r in rows if needle in (r.get("name") or "").lower()]

        if not rows:
            st.info("No leads match these filters. Try clearing them.")
        else:
            st.caption(f"Showing **{len(rows)}** of {s['total']} leads.")
            crm_df = pd.DataFrame(rows)
            crm_df["tier"] = crm_df["dm_score"].fillna(0).astype(int).apply(
                ui.score_tier
            )
            # Essentials by default; full detail behind a toggle for a clean grid.
            show_all_crm = st.toggle(
                "Show all columns", value=False, key="crm_all"
            )
            essential_cols = [
                "name", "tier", "dm_score", "status", "notes",
                "phone", "email", "instagram_handle", "website", "dedup_key",
            ]
            full_cols = [
                "name", "tier", "dm_score", "status", "notes", "phone",
                "email", "instagram_handle", "instagram", "website",
                "niche", "rating", "reviews", "address", "dedup_key",
            ]
            view_cols = full_cols if show_all_crm else essential_cols
            editor_df = crm_df[view_cols].copy()

            edited = st.data_editor(
                editor_df,
                use_container_width=True,
                hide_index=True,
                height=520,
                disabled=[c for c in view_cols if c not in ("status", "notes")],
                column_config={
                    "name": st.column_config.TextColumn("Clinic", width="medium"),
                    "tier": st.column_config.TextColumn("Tier"),
                    "dm_score": st.column_config.ProgressColumn(
                        "DM score", min_value=0, max_value=100, format="%d"
                    ),
                    "status": st.column_config.SelectboxColumn(
                        "Stage", options=crm.STATUSES, required=True
                    ),
                    "notes": st.column_config.TextColumn("Notes", width="medium"),
                    "phone": st.column_config.TextColumn("Phone"),
                    "email": st.column_config.TextColumn("Email"),
                    "instagram_handle": st.column_config.TextColumn("IG handle"),
                    "instagram": st.column_config.LinkColumn("Instagram"),
                    "website": st.column_config.LinkColumn("Website"),
                    "niche": st.column_config.TextColumn("Niche"),
                    "rating": st.column_config.NumberColumn("Rating"),
                    "reviews": st.column_config.NumberColumn("Reviews"),
                    "address": st.column_config.TextColumn("Address"),
                    "dedup_key": None,  # hidden, used as the row key on save
                },
                key="crm_editor",
            )

            b1, b2 = st.columns([1, 1])
            if b1.button("💾 Save changes", type="primary", use_container_width=True):
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

            b2.download_button(
                "⬇️ Export CRM (CSV)",
                crm_df.drop(columns=["dedup_key"]).to_csv(index=False).encode("utf-8"),
                file_name="lumora_crm_export.csv",
                mime="text/csv",
                use_container_width=True,
            )
