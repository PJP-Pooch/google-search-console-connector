
import streamlit as st
import pandas as pd
import openai
import searchconsole
from google_auth_oauthlib.flow import Flow
from apiclient import discovery
from datetime import datetime, timedelta

# === UI Setup ===
st.set_page_config(layout="wide", page_title="GSC Meta Generator", page_icon="🔍")
st.title("🔍 GSC Meta Title & Description Generator")

# === Google OAuth Setup ===
client_id = str(st.secrets["installed"]["client_id"])
client_secret = str(st.secrets["installed"]["client_secret"])
redirect_uri = str(st.secrets["installed"]["redirect_uris"][0])
st.write(f"🔧 Using redirect URI: {redirect_uri}")

credentials = {
    "installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uris": [],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://accounts.google.com/o/oauth2/token",
    }
}

# === Manual OAuth Flow ===
st.markdown("## 🔐 Google Authentication")

flow = Flow.from_client_config(
    credentials,
    scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    redirect_uri=redirect_uri,
)
auth_url, _ = flow.authorization_url(prompt="consent")

st.markdown(f"🔗 [Click here to authenticate with Google]({auth_url})")
auth_code = st.text_input("Paste your authorization code here", key="auth_code_input")
submit_code = st.button("Submit Code", key="submit_auth")

if submit_code and auth_code:
    try:
        flow.fetch_token(code=auth_code)
        credentials = flow.credentials
        service = discovery.build("webmasters", "v3", credentials=credentials)
        account = searchconsole.account.Account(service, credentials)
        st.session_state["account"] = account
        st.success("✅ Successfully authenticated with Google!")
        st.rerun()
    except Exception as e:
        st.error("❌ Google auth failed. Please double-check the code and try again.")
        st.exception(e)
        st.stop()

if "account" not in st.session_state:
    st.stop()

# === Property Selection ===
account = st.session_state["account"]
site_list = account.service.sites().list().execute()
site_urls = [site["siteUrl"] for site in site_list["siteEntry"]]

# === Search Controls ===
st.markdown("## 📅 Search Parameters")

selected_site = st.selectbox("🌐 Select GSC Property", site_urls, key="site_select")

col1, col2, col3 = st.columns(3)
with col1:
    dimension = st.selectbox("Dimension", ["query", "page", "date", "device", "country", "searchAppearance"], key="dimension")
with col2:
    nested_dimension = st.selectbox("Nested dimension", ["none", "query", "page", "date", "device", "country", "searchAppearance"], key="nested1")
with col3:
    nested_dimension_2 = st.selectbox("Nested dimension 2", ["none", "query", "page", "date", "device", "country", "searchAppearance"], key="nested2")

col4, col5 = st.columns(2)
with col4:
    search_type = st.selectbox("Search type", ["web", "image", "video", "news", "googleNews"], key="search_type")

with col5:
    date_range = st.selectbox(
        "Date range",
        ["Last 7 days", "Last 28 days", "Last 3 months", "Last 6 months", "Last 12 months", "Last 16 months", "Custom"],
        index=0,
        key="date_range"
    )

if date_range == "Custom":
    col6, col7 = st.columns(2)
    with col6:
        start_date = st.date_input("Start date", datetime.today() - timedelta(days=28), key="start_date")
    with col7:
        end_date = st.date_input("End date", datetime.today(), key="end_date")
else:
    days_map = {
        "Last 7 days": 7,
        "Last 28 days": 28,
        "Last 3 months": 91,
        "Last 6 months": 182,
        "Last 12 months": 365,
        "Last 16 months": 486
    }
    start_date = datetime.today() - timedelta(days=days_map[date_range])
    end_date = datetime.today()

with st.expander("✨ Advanced Filters", expanded=False):
    filter_conditions = []
    for i in range(1, 4):
        cols = st.columns(3)
        with cols[0]:
            filter_dim = st.selectbox(f"Filter dimension #{i}", ["query", "page", "device", "searchAppearance", "country"], key=f"filter_dim_{i}")
        with cols[1]:
            filter_op = st.selectbox(f"Filter type #{i}", ["contains", "equals", "notContains", "notEquals", "includingRegex", "excludingRegex"], key=f"filter_op_{i}")
        with cols[2]:
            filter_val = st.text_input(f"Keyword(s) #{i}", key=f"filter_val_{i}")
        if filter_val:
            filter_conditions.append((filter_dim, filter_val, filter_op))

# === OpenAI Key Input ===
openai_api_key = st.sidebar.text_input("🔑 Enter your OpenAI API Key", type="password")
if not openai_api_key:
    st.warning("Please enter your OpenAI API Key to continue.")
    st.stop()
openai.api_key = openai_api_key

# === Fetch Data + Meta Generation
if st.button("📊 Fetch GSC Data"):
    with st.spinner("Getting data from Google Search Console..."):
        webproperty = account[selected_site]
        q = webproperty.query.search_type(search_type).range(str(start_date.date()), str(end_date.date()))
        dims = [dimension]
        if nested_dimension != "none":
            dims.append(nested_dimension)
        if nested_dimension_2 != "none":
            dims.append(nested_dimension_2)
        q = q.dimension(*dims)

        for dim, val, op in filter_conditions:
            q = q.filter(dim, val, op)

        df = q.get().to_dataframe()

        if df.empty:
            st.warning("No data returned. Please adjust your filters.")
            st.stop()

        st.subheader("🔍 Raw GSC Data")
        st.dataframe(df.head())

        top_queries = (
            df.groupby("page")
            .apply(lambda g: g.sort_values(by=["clicks", "impressions"], ascending=False).head(3)["query"].tolist())
            .reset_index()
            .rename(columns={0: "top_queries"})
        )

        def generate_meta(url, queries):
            prompt = f"""
            Generate an SEO meta title (max 60 characters) and meta description (max 155 characters) for the page: {url}.
            Base the content on the following top Google Search queries: {', '.join(queries)}.

            Return in this format:
            Title: ...
            Description: ...
            """
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content.strip()

        top_queries["meta"] = top_queries.apply(
            lambda row: generate_meta(row["page"], row["top_queries"]), axis=1
        )

        st.subheader("📝 AI-Generated Meta Tags")
        st.dataframe(top_queries)

        csv = top_queries.to_csv(index=False)
        st.download_button("📥 Download CSV", csv, "meta_tags.csv", "text/csv")
