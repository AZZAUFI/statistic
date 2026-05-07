# --------------------------------------------------------------
# streamlit_app.py
# --------------------------------------------------------------
#  • Streamlit Dashboard – Repairs per laptop model, per month,
#    overall stats & most common issues.
#  • Works on Streamlit Community Cloud (free tier).
# --------------------------------------------------------------

import os
import httpx
import pandas as pd
import plotly.express as px
import streamlit as st
from datetime import date
from typing import List, Dict, Any

# -----------------------------------------------------------------
# 0️⃣  General page config
# -----------------------------------------------------------------
st.set_page_config(
    page_title="Laptop‑Repair Dashboard",
    layout="wide",
    menu_items={
        "About": "Dashboard built with Streamlit, Plotly & Pandas.\n"
                 "Data source = external repair‑ticket API (authenticated).",
    },
)

# -----------------------------------------------------------------
# 1️⃣  Load secret – **must be defined in Streamlit Cloud UI**
# -----------------------------------------------------------------
try:
    API_KEY = st.secrets["api_key"]          # <-- secret name **api_key**
except Exception as exc:
    st.error(
        "❗️ Secret `api_key` not found. "
        "Add it in the Streamlit Cloud **Secrets** UI (Settings → Secrets)."
    )
    st.stop()

# -----------------------------------------------------------------
# 2️⃣  API endpoint (replace with your real host)
# -----------------------------------------------------------------
BASE_URL = "https://api.yourrepairservice.com/v1"   # <<< EDIT THIS LINE
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# -----------------------------------------------------------------
# 3️⃣  Function that pulls *all* pages from the external service.
#    Cached for 5 min to respect rate‑limits.
# -----------------------------------------------------------------
@st.cache_data(ttl=300)  # 5‑min cache
def fetch_all_tickets(start: str | None = None, end: str | None = None) -> List[Dict[str, Any]]:
    """
    Returns a flat list of tickets.
    The external API is expected to have:
        GET /tickets?page=N&received_after=YYYY‑MM‑DD&received_before=…
        → { "tickets": [...], "total_pages": 3 }
    """
    params: Dict[str, Any] = {}
    if start:
        params["received_after"] = start
    if end:
        params["received_before"] = end

    tickets: List[Dict[str, Any]] = []
    with httpx.Client(headers=HEADERS, timeout=30) as client:
        page = 1
        while True:
            try:
                resp = client.get(f"{BASE_URL}/tickets", params={**params, "page": page})
                resp.raise_for_status()
            except httpx.HTTPError as err:
                # surface a friendly message in the UI and stop execution
                st.error(f"🚨 Error while contacting the repair API: **{err}**")
                st.stop()

            data = resp.json()
            tickets.extend(data.get("tickets", []))
            if page >= data.get("total_pages", 1):
                break
            page += 1
    return tickets


# -----------------------------------------------------------------
# 4️⃣  Sidebar – date range filter
# -----------------------------------------------------------------
st.sidebar.header("🗓️ Filters")
col1, col2 = st.sidebar.columns(2)
start_date: date | None = col1.date_input("Start date", value=None)
end_date:   date | None = col2.date_input("End date",   value=None)

# Convert to ISO strings for the API call
start_iso = start_date.isoformat() if start_date else None
end_iso   = end_date.isoformat()   if end_date   else None

# -----------------------------------------------------------------
# 5️⃣  Load the data (with a spinner so the user knows we’re busy)
# -----------------------------------------------------------------
with st.spinner("🔄 Pulling ticket data from the external API…"):
    raw_tickets = fetch_all_tickets(start_iso, end_iso)

if not raw_tickets:
    st.warning("🤷 No tickets returned for the selected period.")
    st.stop()

# -----------------------------------------------------------------
# 6️⃣  Convert JSON → tidy DataFrame
# -----------------------------------------------------------------
df = pd.DataFrame(raw_tickets)

# ---- Expected columns – adapt if your API uses different names ----
# received_at, closed_at, status, laptop_model, issue_description
df["received_at"] = pd.to_datetime(df["received_at"])
df["month"] = df["received_at"].dt.to_period("M").astype(str)

df["model"] = df["laptop_model"].fillna("Unknown")
df["issue"] = df["issue_description"].fillna("Unspecified")

# -----------------------------------------------------------------
# 7️⃣  Summary cards (top of the page)
# -----------------------------------------------------------------
total_tickets = len(df)
closed_tickets = (df["status"] == "closed").sum()
open_tickets   = total_tickets - closed_tickets

if closed_tickets:
    df_closed = df[df["status"] == "closed"].copy()
    df_closed["closed_at"] = pd.to_datetime(df_closed["closed_at"])
    df_closed["resolution_days"] = (df_closed["closed_at"] - df_closed["received_at"]).dt.days
    avg_resolution = round(df_closed["resolution_days"].mean(), 1)
else:
    avg_resolution = None

col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("Total tickets", total_tickets)
col_b.metric("Closed", closed_tickets)
col_c.metric("Open", open_tickets)
col_d.metric(
    "Avg. resolution (days)",
    f"{avg_resolution:.1f}" if avg_resolution is not None else "—",
)

st.divider()

# -----------------------------------------------------------------
# 8️⃣  Chart 1 – Monthly repairs per model (stacked bar)
# -----------------------------------------------------------------
st.subheader("🔧 Repairs per Model – Monthly")
monthly_counts = (
    df.groupby(["month", "model"])
    .size()
    .reset_index(name="count")
)

fig_bar = px.bar(
    monthly_counts,
    x="month",
    y="count",
    color="model",
    title="Monthly volume by model",
    labels={"month": "Month", "count": "Repairs"},
    height=500,
    barmode="stack",
)
st.plotly_chart(fig_bar, use_container_width=True)

st.divider()

# -----------------------------------------------------------------
# 9️⃣  Chart 2 – Top 10 issues (donut)
# -----------------------------------------------------------------
st.subheader("🛠️ Top 10 Reported Issues (All Models)")
top_issues = (
    df["issue"]
    .value_counts()
    .reset_index()
    .rename(columns={"index": "issue", "issue": "count"})
    .head(10)
)

fig_donut = px.pie(
    top_issues,
    names="issue",
    values="count",
    hole=0.4,
    title="Most frequent failure symptoms",
)
st.plotly_chart(fig_donut, use_container_width=True)

st.divider()

# -----------------------------------------------------------------
# 🔎  Optional drill‑down – choose a model
# -----------------------------------------------------------------
st.subheader("🔍 Model‑drill‑down")
selected_model = st.selectbox(
    "Select model (or “All”)",
    options=["All"] + sorted(df["model"].unique()),
)

if selected_model != "All":
    df_m = df[df["model"] == selected_model]

    # ---- Issues for this model ----
    top_m_issues = (
        df_m["issue"]
        .value_counts()
        .reset_index()
        .rename(columns={"index": "issue", "issue": "count"})
        .head(10)
    )
    fig_issue = px.pie(
        top_m_issues,
        names="issue",
        values="count",
        hole=0.3,
        title=f"Top issues for {selected_model}",
    )
    st.plotly_chart(fig_issue, use_container_width=True)

    # ---- Monthly trend for this model (line) ----
    month_model = (
        df_m.groupby("month")
        .size()
        .reset_index(name="count")
        .sort_values("month")
    )
    fig_line = px.line(
        month_model,
        x="month",
        y="count",
        markers=True,
        title=f"Monthly volume for {selected_model}",
    )
    st.plotly_chart(fig_line, use_container_width=True)

# -----------------------------------------------------------------
# 10️⃣  CSV download (sidebar)
# -----------------------------------------------------------------
st.sidebar.download_button(
    label="📥 Download raw tickets (CSV)",
    data=df.to_csv(index=False).encode("utf-8"),
    file_name="repair_tickets.csv",
    mime="text/csv",
)

# -----------------------------------------------------------------
# 11️⃣  Footer
# -----------------------------------------------------------------
st.caption(
    """
    **Built with** Streamlit 🧊 + Plotly 📈 + Pandas 🐼.  
    Data source: external repair‑ticket API (authenticated with a secret key).  
    """
)
