import streamlit as st
import pandas as pd
from openai import OpenAI
import searchconsole
from google_auth_oauthlib.flow import Flow
from apiclient import discovery
from datetime import datetime, timedelta

st.set_page_config(layout="wide", page_title="Top Queries with AI Keywords", page_icon="🔍")
st.title("🔍 GSC: Top Queries + AI Primary & Secondary Keywords (Bulk Mode)")

# === Google OAuth Setup ===
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

flow = Flow.from_client_config(
    credentials,
    scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    redirect_uri=redirect_uri,
)
auth_url, _ = flow.authorization_url(prompt="consent")

st.markdown("## 🔐 Google Authentication")
st.markdown(f"[Click here to authenticate with Google]({auth_url})")
auth_code = st.text_input("Paste the authorization code from the URL")
submit_code = st.button("Submit Code")

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

# === OpenAI Key (new client)
openai_key = st.sidebar.text_input("🔑 OpenAI API Key", type="password")
if not openai_key:
    st.warning("Please enter your OpenAI API Key to continue.")
    st.stop()
client = OpenAI(api_key=openai_key)

# === GSC Property and Date Selection
account = st.session_state["account"]
site_list = account.service.sites().list().execute()
site_urls = [site["siteUrl"] for site in site_list["siteEntry"]]
selected_site = st.selectbox("Select GSC Property", site_urls)

date_range = st.selectbox("Date range", ["Last 7 days", "Last 28 days", "Last 3 months"], index=1)
days_map = {"Last 7 days": 7, "Last 28 days": 28, "Last 3 months": 91}
start_date = datetime.today() - timedelta(days=days_map[date_range])
end_date = datetime.today()

# === Fetch GSC + Bulk Prompt
if st.button("📊 Fetch and Generate Keywords"):
    with st.spinner("Fetching GSC data..."):
        webproperty = account[selected_site]
        df = (
            webproperty.query
            .range(str(start_date.date()), str(end_date.date()))
            .dimension("page", "query")
            .search_type("web")
            .limit(5000)
            .get()
            .to_dataframe()
        )

        if df.empty:
            st.warning("No data returned.")
            st.stop()

        top_pages = df.groupby("page").agg({"clicks": "sum"}).reset_index()
        top_100_pages = top_pages.sort_values("clicks", ascending=False).head(100)["page"]
        df_filtered = df[df["page"].isin(top_100_pages)].copy()

    with st.spinner("Building prompt and calling OpenAI..."):
        bulk_prompt = """You are an SEO assistant. For each page below, return the best primary keyword (highest clicks) and a different secondary keyword (highest impressions).

"""
        for page, group in df_filtered.groupby("page"):
            queries = group.sort_values(by=["clicks", "impressions"], ascending=False)[["query", "clicks", "impressions"]]
            bulk_prompt += f"Page: {page}\n"
            bulk_prompt += queries.to_string(index=False)
            bulk_prompt += "\nPrimary: \nSecondary: \n\n"

        try:
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": bulk_prompt}]
            )
            bulk_result = response.choices[0].message.content.strip()
        except Exception as e:
            bulk_result = f"❌ Error during OpenAI request: {e}"

    st.subheader("📋 AI-Generated Keywords")
    st.text_area("Output", bulk_result, height=600)
    st.download_button("📥 Download TXT", bulk_result, "ai_keywords_bulk.txt", "text/plain")
