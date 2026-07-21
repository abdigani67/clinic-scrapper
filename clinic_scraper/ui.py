"""Presentation helpers for the Streamlit app: brand, theme CSS, hero, badges.

Purely cosmetic — none of this touches the scraping/scoring/CRM logic.
"""

from __future__ import annotations

APP_NAME = "Runova"
APP_TAGLINE = "Clinic Lead Intelligence for your AI receptionist"
APP_ICON = "💎"

# Brand palette.
_VIOLET = "#7C3AED"
_VIOLET_DARK = "#5B21B6"
_INK = "#1E1B2E"

CSS = f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

  html, body, [class*="css"], .stMarkdown, .stTextInput, .stButton {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  }}

  /* Hide the prototype-y Streamlit chrome */
  #MainMenu {{visibility: hidden;}}
  footer {{visibility: hidden;}}
  [data-testid="stToolbar"] {{display: none;}}
  [data-testid="stDecoration"] {{display: none;}}
  [data-testid="stStatusWidget"] {{display: none;}}

  /* Always keep the sidebar expand/collapse control visible and reachable */
  [data-testid="stSidebarCollapsedControl"],
  [data-testid="stSidebarCollapseButton"],
  [data-testid="collapsedControl"] {{
    display: flex !important; visibility: visible !important; opacity: 1 !important;
    z-index: 999999 !important;
  }}

  .block-container {{padding-top: 1.4rem; max-width: 1280px;}}

  h1, h2, h3 {{font-weight: 800; letter-spacing: -0.02em; color: {_INK};}}

  /* Hero banner */
  .runova-hero {{
    background: linear-gradient(120deg, {_VIOLET_DARK} 0%, {_VIOLET} 55%, #A855F7 100%);
    border-radius: 20px;
    padding: 1.8rem 2.2rem;
    margin-bottom: 1.4rem;
    color: #fff;
    box-shadow: 0 18px 40px -16px rgba(124,58,237,0.55);
  }}
  .runova-hero .brand {{
    font-size: 0.82rem; font-weight: 700; letter-spacing: 0.18em;
    text-transform: uppercase; opacity: 0.85;
  }}
  .runova-hero h1 {{
    color: #fff; font-size: 2.1rem; font-weight: 900; margin: 0.15rem 0 0.35rem;
  }}
  .runova-hero p {{margin: 0; font-size: 1.02rem; opacity: 0.92; font-weight: 400;}}

  /* Premium metric cards */
  [data-testid="stMetric"] {{
    background: #fff;
    border: 1px solid #ECEAF6;
    border-radius: 16px;
    padding: 1rem 1.2rem;
    box-shadow: 0 10px 26px -18px rgba(30,27,46,0.35);
    transition: transform .15s ease, box-shadow .15s ease;
  }}
  [data-testid="stMetric"]:hover {{
    transform: translateY(-2px);
    box-shadow: 0 16px 34px -18px rgba(124,58,237,0.45);
  }}
  [data-testid="stMetricValue"] {{font-weight: 800; color: {_INK};}}
  [data-testid="stMetricLabel"] {{font-weight: 600; opacity: 0.7;}}

  /* Buttons */
  .stButton > button {{
    border-radius: 12px; font-weight: 600; border: 1px solid #E4E1F2;
  }}
  .stButton > button[kind="primary"] {{
    background: linear-gradient(120deg, {_VIOLET_DARK}, {_VIOLET});
    border: none; box-shadow: 0 10px 24px -12px rgba(124,58,237,0.7);
  }}

  /* Tabs */
  .stTabs [data-baseweb="tab-list"] {{gap: 0.4rem;}}
  .stTabs [data-baseweb="tab"] {{font-weight: 600;}}

  /* Dataframe rounding */
  [data-testid="stDataFrame"] {{border-radius: 14px; overflow: hidden;}}
</style>
"""


def hero_html() -> str:
    return f"""
    <div class="runova-hero">
      <div class="brand">{APP_ICON} {APP_NAME}</div>
      <h1>{APP_TAGLINE}</h1>
      <p>Find, score &amp; win aesthetic clinics — with email and socials — then
      work them through your pipeline.</p>
    </div>
    """


def score_tier(score: int) -> str:
    """Human-readable badge for a DM-ready score."""
    if score >= 80:
        return "🟢 Hot"
    if score >= 60:
        return "🟡 Warm"
    if score >= 40:
        return "🟠 Cool"
    return "⚪ Cold"
