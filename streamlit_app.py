
import streamlit as st
import pandas as pd
import searchconsole
from google_auth_oauthlib.flow import Flow
from apiclient import discovery
from datetime import datetime, timedelta

st.set_page_config(layout="wide", page_title="Top Queries Per Page", page_icon="🔍")
st.title("🔍 GSC: Top Queries (Top 100 Pages)")

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

# === Date range
date_range = st.selectbox("Date range", ["Last 7 days", "Last 28 days", "Last 3 months"], index=1)
days_map = {"Last 7 days": 7, "Last 28 days": 28, "Last 3 months": 91}
start_date = datetime.today() - timedelta(days=days_map[date_range])
end_date = datetime.today()

# === Fetch and Limit to Top 100 Pages
if st.button("📊 Fetch Top Queries"):
    with st.spinner("Fetching top 100 pages with nested queries..."):
        webproperty = account[selected_site]
        df = (
            webproperty.query.range(str(start_date.date()), str(end_date.date()))
            .dimension("page", "query")
            .search_type("web")
            .limit(5000)
            .get()
            .to_dataframe()
        )

        if df.empty:
            st.warning("No data returned. Please adjust your filters.")
            st.stop()

        # Aggregate top pages first
        page_clicks = df.groupby("page").agg({"clicks": "sum"}).reset_index()
        top_pages = page_clicks.sort_values("clicks", ascending=False).head(100)["page"]

        df_filtered = df[df["page"].isin(top_pages)]

        # Reorder columns for clarity
        df_filtered = df_filtered[["page", "query", "clicks", "impressions", "position", "ctr"]]
        df_filtered.columns = ["Page", "Query", "Clicks", "Impressions", "Avg Position", "CTR"]

        st.subheader("📄 Top Queries for Top 100 Pages")
        st.dataframe(df_filtered)

        csv = df_filtered.to_csv(index=False)
        st.download_button("📥 Download CSV", csv, "top_100_pages_queries.csv", "text/csv")
