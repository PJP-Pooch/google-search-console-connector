import streamlit as st
import pandas as pd
import searchconsole
from google_auth_oauthlib.flow import Flow
from apiclient.discovery import build
from openai import OpenAI
import re

st.set_page_config(page_title="GSC Keyword Extractor", layout="wide")

# Session state setup
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

# UI
st.title("🔐 GSC Keyword Extractor (Manual Auth Flow)")

# OAuth credentials
client_id = st.secrets["installed"]["client_id"]
client_secret = st.secrets["installed"]["client_secret"]
redirect_uri = st.secrets["installed"]["redirect_uris"][0]
credentials = {
    "installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uris": [],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://accounts.google.com/o/oauth2/token"
    }
}

flow = Flow.from_client_config(
    credentials,
    scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    redirect_uri=redirect_uri
)

auth_url, _ = flow.authorization_url(prompt="consent")

st.markdown("### Step 1: Sign in with Google")
st.markdown(f"[🔗 Click here to authorize with Google]({auth_url})", unsafe_allow_html=True)

st.markdown("### Step 2: Paste the `code` from the redirect URL here")
code_input = st.text_input("Paste the `code` from the redirected URL", key="auth_code")

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

# Sidebar Filters
st.sidebar.markdown("### 🔍 Page Filter")
page_filter_type = st.sidebar.selectbox("Page filter type", ["contains", "starts with", "ends with", "regex match", "doesn't match regex"])
page_filter_value = st.sidebar.text_input("Page filter value(s) (comma-separated)", st.session_state["page_filter_value"])

st.sidebar.markdown("### 🔍 Query Filter")
query_filter_type = st.sidebar.selectbox("Query filter type", ["contains", "starts with", "ends with", "regex match", "doesn't match regex"])
query_filter_value = st.sidebar.text_input("Query filter value(s) (comma-separated)", st.session_state["query_filter_value"])

if st.sidebar.button("🔁 Reset Filters"):
    st.session_state["page_filter_value"] = ""
    st.session_state["query_filter_value"] = ""

# GSC Data Section
if "account" in st.session_state:
    def get_sites(account):
        return account.service.sites().list().execute()

    site_list = get_sites(st.session_state["account"])
    site_urls = [site["siteUrl"] for site in site_list["siteEntry"]]
    selected_site = st.selectbox("🌐 Select GSC Property", site_urls)

    timescale = st.selectbox("Date range", ["Last 7 days", "Last 28 days", "Last 3 months", "Last 12 months"])
    days = {"Last 7 days": -7, "Last 28 days": -28, "Last 3 months": -90, "Last 12 months": -365}[timescale]

    if st.button("📊 Fetch GSC Data"):
        with st.spinner("Fetching from Google Search Console..."):
            webproperty = st.session_state["account"][selected_site]
            df = (
                webproperty.query.range("today", days=days)
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
            st.success("✅ GSC data fetched!")
            st.dataframe(df.head(50))

            csv = df.to_csv(index=False)
            st.download_button("📥 Download CSV", csv, "output.csv", "text/csv")
