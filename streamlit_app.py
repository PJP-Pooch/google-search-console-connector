import streamlit as st
import pandas as pd
import searchconsole
from google_auth_oauthlib.flow import Flow
from apiclient.discovery import build
from openai import OpenAI
import re
from datetime import date, timedelta

st.set_page_config(page_title="GSC Wee Extractor", layout="wide")

# Session state defaults
if "page_filter_value" not in st.session_state:
    st.session_state["page_filter_value"] = ""
if "query_filter_value" not in st.session_state:
    st.session_state["query_filter_value"] = ""

# Helper functions
def safe_regex_match(series, pattern, invert=False):
    try:
        matched = series.str.match(pattern)
        return ~matched if invert else matched
    except re.error:
        return pd.Series([False] * len(series))

def apply_page_filter(df, filter_type, filter_value):
    values = [v.strip() for v in filter_value.split(",") if v.strip()]
    if not values:
        return df
    if filter_type == "contains":
        return df[df["page"].str.contains('|'.join(values), case=False, na=False)]
    elif filter_type == "starts with":
        return df[df["page"].str.startswith(tuple(values))]
    elif filter_type == "ends with":
        return df[df["page"].str.endswith(tuple(values))]
    elif filter_type == "regex match":
        return df[safe_regex_match(df["page"], '|'.join(values))]
    elif filter_type == "doesn't match regex":
        return df[safe_regex_match(df["page"], '|'.join(values), invert=True)]
    return df

def apply_query_filter(df, filter_type, filter_value):
    values = [v.strip() for v in filter_value.split(",") if v.strip()]
    if not values:
        return df
    if filter_type == "contains":
        return df[df["query"].str.contains('|'.join(values), case=False, na=False)]
    elif filter_type == "starts with":
        return df[df["query"].str.startswith(tuple(values))]
    elif filter_type == "ends with":
        return df[df["query"].str.endswith(tuple(values))]
    elif filter_type == "regex match":
        return df[safe_regex_match(df["query"], '|'.join(values))]
    elif filter_type == "doesn't match regex":
        return df[safe_regex_match(df["query"], '|'.join(values), invert=True)]
    return df

def chunk_dict(d, size):
    items = list(d.items())
    for i in range(0, len(items), size):
        yield dict(items[i:i + size])

def select_primary_secondary_keywords(df):
    results = []
    for page, group in df.groupby("page"):
        total_clicks = group["clicks"].sum()

        top_click = group.sort_values(by="clicks", ascending=False).iloc[0]
        group_excl_click = group[group["query"] != top_click["query"]]

        if not group_excl_click.empty:
            top_impression = group_excl_click.sort_values(by="impressions", ascending=False).iloc[0]
        else:
            top_impression = top_click

        results.append({
            "page": page,
            "total_clicks": total_clicks,
            "primary_keyword": top_click["query"],
            "primary_clicks": top_click["clicks"],
            "primary_impressions": top_click["impressions"],
            "secondary_keyword": top_impression["query"],
            "secondary_clicks": top_impression["clicks"],
            "secondary_impressions": top_impression["impressions"]
        })

    return pd.DataFrame(results).sort_values(by="total_clicks", ascending=False)


# OAuth config
client_id = st.secrets["installed"]["client_id"]
client_secret = st.secrets["installed"]["client_secret"]
redirect_uri = st.secrets["installed"]["redirect_uris"][0]

flow = Flow.from_client_config(
    {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://accounts.google.com/o/oauth2/token"
        }
    },
    scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    redirect_uri=redirect_uri
)

# App UI
st.title("🔐 GSC Keyword Extractor")
auth_url, _ = flow.authorization_url(prompt="consent")
st.markdown("### Step 1: Authorize with Google")
st.markdown(f"[🔗 Click here to authorize]({auth_url})", unsafe_allow_html=True)
code_input = st.text_input("Step 2: Paste the authorization code here")

if code_input and "account" not in st.session_state:
    try:
        flow.fetch_token(code=code_input)
        credentials = flow.credentials
        service = build("webmasters", "v3", credentials=credentials)
        account = searchconsole.account.Account(service, credentials)
        st.session_state["account"] = account
        st.rerun()
    except Exception as e:
        st.error("❌ Authentication failed. Please check your code.")
        st.exception(e)
        st.stop()

# Sidebar filters
st.sidebar.markdown("### Page Filter")
if st.sidebar.button("🔁 Reset Filters"):
    st.session_state["page_filter_value"] = ""
    st.session_state["query_filter_value"] = ""

page_filter_type = st.sidebar.selectbox("Page filter type", ["contains", "starts with", "ends with", "regex match", "doesn't match regex"])
page_filter_value = st.sidebar.text_input("Page filter value(s)", key="page_filter_value")

st.sidebar.markdown("### Query Filter")
query_filter_type = st.sidebar.selectbox("Query filter type", ["contains", "starts with", "ends with", "regex match", "doesn't match regex"])
query_filter_value = st.sidebar.text_input("Query filter value(s)", key="query_filter_value")

# Main logic
if "account" in st.session_state:
    site_list = st.session_state["account"].service.sites().list().execute()

    if "siteEntry" in site_list:
        site_urls = [site["siteUrl"] for site in site_list["siteEntry"]]

        with st.form("gsc_form"):
            selected_site = st.selectbox("🌐 Select GSC Property", site_urls)
            timescale = st.selectbox("Date range", ["Last 7 days", "Last 28 days", "Last 3 months", "Last 12 months"])
            submit_gsc = st.form_submit_button("📊 Fetch GSC Data")

        if submit_gsc:
            days_map = {"Last 7 days": -7, "Last 28 days": -28, "Last 3 months": -90, "Last 12 months": -365}
            days = days_map[timescale]
            end_date = date.today()
            start_date = end_date + timedelta(days=days)
            with st.spinner("Fetching from Google Search Console..."):
                webproperty = st.session_state["account"][selected_site]
                df = (
                    webproperty.query.range(start_date.isoformat(), end_date.isoformat())
                    .dimension("page", "query")
                    .get()
                    .to_dataframe()
                )
                df = apply_page_filter(df, page_filter_type, page_filter_value)
                df = apply_query_filter(df, query_filter_type, query_filter_value)

                if df.empty:
                    st.warning("No data returned. Adjust your filters.")
                    st.stop()

                st.session_state["gsc_data"] = df
                st.success("✅ Data fetched!")
                st.dataframe(df.head(50))
                csv = df.to_csv(index=False)
                st.download_button("📥 Download CSV", csv, "output.csv", "text/csv")

        # ✅ Show keyword extraction and data preview if available
        if "gsc_data" in st.session_state:
            st.markdown("### Step 2: Extract Keywords per Page")

            if st.button("🔎 Extract Keywords"):
                df = st.session_state["gsc_data"]
                df_keywords = select_primary_secondary_keywords(df)
                st.session_state["keywords_data"] = df_keywords

                # ✅ Display/download outside the button
                if "keywords_data" in st.session_state:
                    st.subheader("📋 Primary & Secondary Keywords")
                    st.dataframe(st.session_state["keywords_data"])
                    csv_kw = st.session_state["keywords_data"].to_csv(index=False)
                    st.download_button("📥 Download Keywords CSV", csv_kw, "keywords.csv", "text/csv")

            st.markdown("### GSC data")
            st.dataframe(df.head(50))
            csv = df.to_csv(index=False)
            st.download_button("📥 Download CSV", csv, "output.csv", "text/csv")

    else:
        st.warning("No GSC properties found.")

