# ✨ Aesthetic Clinic Lead Scraper

Find aesthetic clinics, med spas and cosmetic practices — with **email** and
**social links** — so you can pitch them your AI receptionist / DM service.

It pulls clinics from the **Google Places API (New)**, then visits each clinic's
website to grab the email and Instagram/Facebook/TikTok links that Google
doesn't expose. Results de-duplicate automatically and export to **CSV + Excel**.

| Field | Source |
|---|---|
| Name, Address, Phone, Website, Rating, Reviews | Google Places |
| Email, Instagram, Facebook, TikTok | Clinic website crawl |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then paste your Google Places API key
```

Get a key: enable **Places API (New)** in the
[Google Cloud Console](https://console.cloud.google.com/apis/library/places.googleapis.com),
then create an API key. New Google Cloud accounts include free monthly credit.

## Use it

### Web UI (recommended)

```bash
streamlit run app.py
```

Type a term, list your target cities, and hit **Scrape leads**. Filter to only
leads that have an email or an Instagram, then download CSV/Excel.

### Command line

```bash
# One search
python -m clinic_scraper.cli "aesthetic clinic in Austin TX"

# Same term across several cities
python -m clinic_scraper.cli "med spa" --city "Miami FL" --city "Dallas TX"

# Faster, no website enrichment
python -m clinic_scraper.cli "botox clinic London" --no-enrich --max 40
```

Output lands in `output/leads_<timestamp>.csv` and `.xlsx`.

## How it works

```
queries ─▶ places.search_clinics ─▶ dedupe ─▶ enrich (website crawl) ─▶ CSV/Excel
```

- `clinic_scraper/places.py` — Google Places Text Search (handles pagination).
- `clinic_scraper/enrich.py` — fetches homepage + contact pages, extracts email & socials.
- `clinic_scraper/pipeline.py` — orchestration + de-duplication (by Google place id).
- `clinic_scraper/export.py` — CSV and styled Excel output.

## Notes on responsible use

- Scrapes only **publicly listed business** contact details, for B2B outreach.
- Enrichment uses a descriptive User-Agent and short, sequential requests — it
  does not hammer sites. Be reasonable with volume.
- When you email/DM these clinics, follow anti-spam rules (CAN-SPAM, GDPR/PECR,
  etc.): identify yourself and offer an opt-out.

## Tips for your use case (AI receptionist outreach)

- Sort/filter for clinics **with an Instagram** — they're your warmest leads,
  since your pitch is "I'll answer your DMs 24/7."
- Run city by city and keep your CSVs; re-running merges cleanly because leads
  de-dupe on Google place id.
