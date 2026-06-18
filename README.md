# ✨ Aesthetic Clinic Lead Scraper + CRM

Find aesthetic clinics, med spas and cosmetic practices — with **email** and
**social links** — score them for your AI receptionist / DM service, and work
them through a **built-in CRM pipeline**.

It pulls clinics from the **Google Places API (New)**, visits each clinic's
website to grab the email and Instagram/Facebook/TikTok links Google doesn't
expose, classifies each into an **aesthetic niche**, ranks it with a
**DM-ready score**, and exports to **CSV + Excel** or pushes into a local CRM.

| Field | Source |
|---|---|
| Name, Address, Phone, Website, Rating, Reviews | Google Places |
| Email, Instagram, Facebook, TikTok | Clinic website crawl |
| Niche, DM-ready score | Derived (see below) |

## Niche filtering

Every result is classified by **name** into niches — Injectables, Laser & Skin,
Facials & Skincare, Med Spa, Body Contouring, Cosmetic Surgery, Wellness & IV,
Dermatology. Non-targets that creep into "clinic" searches (dentists, vets,
gyms, nail salons, etc.) are dropped automatically. Filter to specific niches
with `--niche` (CLI) or the multiselect (UI).

## DM-ready score (0–100)

Ranks how good a fit a clinic is for an "I answer your DMs 24/7" pitch:

| Signal | Points | Why |
|---|---|---|
| Has Instagram | 35 | Core — they have a DM inbox to answer |
| Has email | 15 | You can actually reach them |
| Confirmed niche | 12 | Real aesthetic target |
| Has Facebook | 10 | Another DM channel |
| Has website | 8 | Established presence |
| Review volume | up to 20 | Busier clinic = more DMs = more pain |
| Rating | up to 5 | Real, active demand |

Tune the weights in `clinic_scraper/scoring.py`. Filter with `--min-score`.

## Built-in CRM

Push leads into a local **SQLite** CRM (`leads.db`) with a status pipeline
(`new → contacted → replied → demo → won → lost`) and per-lead notes. Re-scraping
refreshes the scraped fields but **preserves your status and notes**, so you can
re-run searches without losing your work. Manage it from the **CRM tab** in the
web UI, or push from the CLI with `--to-crm`.

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

**Scrape tab:** type a term, list cities, set niche/score filters, hit
**Scrape leads**, then download CSV/Excel or **Push to CRM**.
**CRM tab:** filter by status/niche/score and edit each lead's status and notes
inline, then **Save changes**.

### Command line

```bash
# One search
python -m clinic_scraper.cli "aesthetic clinic in Austin TX"

# Same term across several cities
python -m clinic_scraper.cli "med spa" --city "Miami FL" --city "Dallas TX"

# Only injectables + med spas, score >= 50, straight into the CRM
python -m clinic_scraper.cli "med spa Austin" \
    --niche "Injectables" --niche "Med Spa" --min-score 50 --to-crm

# Faster, no website enrichment
python -m clinic_scraper.cli "botox clinic London" --no-enrich --max 40
```

Output lands in `output/leads_<timestamp>.csv` and `.xlsx`.

## How it works

```
queries ─▶ search ─▶ dedupe ─▶ niche filter ─▶ enrich ─▶ score ─▶ CSV/Excel/CRM
```

- `clinic_scraper/places.py` — Google Places Text Search (handles pagination).
- `clinic_scraper/niche.py` — classifies niches, drops non-targets.
- `clinic_scraper/enrich.py` — fetches homepage + contact pages, extracts email & socials.
- `clinic_scraper/scoring.py` — the DM-ready score (tunable weights).
- `clinic_scraper/pipeline.py` — orchestration + de-duplication (by Google place id).
- `clinic_scraper/crm.py` — SQLite CRM (upsert preserves status/notes).
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
