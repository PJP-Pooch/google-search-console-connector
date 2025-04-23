
import streamlit as st
import pandas as pd
import openai
import searchconsole
from google_auth_oauthlib.flow import Flow
from apiclient import discovery
from datetime import datetime, timedelta

st.set_page_config(layout="wide", page_title="Top Queries Exporter", page_icon="🔍")
st.title("🔍 GSC: Top 10 Queries Per Page")

client_id = str(st.secrets["installed"]["client_id"])
client_secret = str(st.secrets["installed"]["client_secret"])
redirect_uri = str(st.secrets["installed"]["redirect_uris"][0])

credentials = {
    "installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uris": [],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://accounts.google.com/o/oauth2/token",
    }
}

# === Manual OAuth ===
flow = Flow.from_client_config(
    credentials,
    scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    redirect_uri=redirect_uri,
)
auth_url, _ = flow.authorization_url(prompt="consent")

st.markdown("## 🔐 Google Authentication")
st.markdown(f"[Click here to authenticate with Google]({auth_url})")
auth_code = st.text_input("Paste the authorization code from the URL", key="auth_code_input")
submit_code = st.button("Submit Code", key="submit_auth")

if submit_code and auth_code:
    try:
        flow.fetch_token(code=auth_code)
        credentials = flow.credentials
        service = discovery.build("webmasters", "v3", credentials=credentials)
        account = searchconsole.account.Account(service, credentials)
        st.session_state["account"] = account
        st.success("✅ Authenticated with Google!")
        st.rerun()
    except Exception as e:
        st.error("❌ Auth failed.")
        st.exception(e)
        st.stop()

if "account" not in st.session_state:
    st.stop()

account = st.session_state["account"]
site_list = account.service.sites().list().execute()
site_urls = [site["siteUrl"] for site in site_list["siteEntry"]]
selected_site = st.selectbox("Select GSC Property", site_urls, key="site_select")

# === Date range presets
date_range = st.selectbox("Date range", ["Last 7 days", "Last 28 days", "Last 3 months"], index=1)
days_map = {"Last 7 days": 7, "Last 28 days": 28, "Last 3 months": 91}
start_date = datetime.today() - timedelta(days=days_map[date_range])
end_date = datetime.today()

# === Page-level filter
with st.expander("🔎 Filter by Page URL"):
    page_filter = st.text_input("Only include pages containing...", value="", placeholder="e.g. /blog", key="page_filter")

# === Fetch + Group ===
if st.button("📊 Fetch Top Queries"):
    with st.spinner("Fetching data..."):
        webproperty = account[selected_site]
        q = (
            webproperty.query.range(str(start_date.date()), str(end_date.date()))
            .dimension("page", "query")
            .search_type("web")
        )

        if page_filter.strip():
            q = q.filter("page", page_filter.strip(), "contains")

        df = q.get().to_dataframe()

        if df.empty:
            st.warning("No data found.")
            st.stop()

        top_queries = (
            df.groupby("page")
            .apply(lambda g: g.sort_values(by="clicks", ascending=False).head(10)["query"].tolist())
            .reset_index()
            .rename(columns={0: "top_10_queries"})
        )

        st.subheader("📄 Top 10 Queries per Page")
        st.dataframe(top_queries)

        csv = top_queries.to_csv(index=False)
        st.download_button("📥 Download CSV", csv, "top_queries.csv", "text/csv")
