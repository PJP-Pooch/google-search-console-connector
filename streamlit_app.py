import streamlit as st
import pandas as pd
import searchconsole
st.set_page_config(page_title="GSC Keyword Extractor", layout="wide")
from google_auth_oauthlib.flow import Flow
from apiclient.discovery import build
import openai
from openai import OpenAI
st.title("🔐 GSC Keyword Extractor (Manual Auth Flow)")
# Load OAuth credentials
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
# Fetch token manually
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
if "account" in st.session_state:
    account = st.session_state["account"]
    site_list = account.service.sites().list().execute()
    site_urls = [site["siteUrl"] for site in site_list["siteEntry"]]
    selected_site = st.selectbox("🌐 Select GSC Property", site_urls)
    # ✅ Advanced Page Filter Options
st.sidebar.markdown("### 🔍 Page Filter")
page_filter_type = st.sidebar.selectbox("Page filter type", ["contains", "starts with", "ends with", "regex match", "doesn’t match regex"])
page_filter_value = st.sidebar.text_input("Page filter value", "/products")
# ✅ Advanced Query Filter Options
st.sidebar.markdown("### 🔍 Query Filter")
query_filter_type = st.sidebar.selectbox("Query filter type", ["contains", "starts with", "ends with", "regex match", "doesn’t match regex"])
query_filter_value = st.sidebar.text_input("Query filter value", "pooch")

# Date range presets
timescale = st.selectbox("Date range", [
    "Last 7 days", "Last 28 days", "Last 3 months", "Last 12 months"
])
if timescale == "Last 7 days":
    days = -7
elif timescale == "Last 28 days":
    days = -28
elif timescale == "Last 3 months":
    days = -90
elif timescale == "Last 12 months":
    days = -365
if st.button("📊 Fetch and Generate Keywords"):
    with st.spinner("⚙️ Generating keywords..."):
        webproperty = account[selected_site]
        df = (
            webproperty.query.range("today", days=days)
            .dimension("page", "query")
            .get()
            .to_dataframe()
        )
        # ✅ Apply page filter
        if page_filter_value:
            if page_filter_type == "contains":
                df = df[df["page"].str.contains(page_filter_value, case=False, na=False)]
            elif page_filter_type == "starts with":
                df = df[df["page"].str.startswith(page_filter_value)]
            elif page_filter_type == "ends with":
                df = df[df["page"].str.endswith(page_filter_value)]
            elif page_filter_type == "regex match":
                df = df[df["page"].str.match(page_filter_value)]
            elif page_filter_type == "doesn’t match regex":
                df = df[~df["page"].str.match(page_filter_value)]
        # ✅ Apply query filter
        if query_filter_value:
            if query_filter_type == "contains":
                df = df[~df["query"].str.contains(query_filter_value, case=False, na=False)]
            elif query_filter_type == "starts with":
                df = df[~df["query"].str.startswith(query_filter_value)]
            elif query_filter_type == "ends with":
                df = df[~df["query"].str.endswith(query_filter_value)]
            elif query_filter_type == "regex match":
                df = df[~df["query"].str.match(query_filter_value)]
            elif query_filter_type == "doesn’t match regex":
                df = df[df["query"].str.match(query_filter_value)]
        if df.empty:
            st.warning("No data returned. Adjust your filters.")
            st.stop()
        top_queries = (
            df.groupby("page")
            .apply(lambda g: g.sort_values(by=["clicks", "impressions"], ascending=False).head(10))
            .reset_index(drop=True)
        )
        st.subheader("🔍 Preview: Top Queries by Page")
        st.dataframe(top_queries.head(50))
    
# 🔑 Require OpenAI API Key only after GSC data is ready
openai_api_key = st.sidebar.text_input("Enter your OpenAI API Key", type="password")
if not openai_api_key:
    st.warning("Please enter your OpenAI API Key to generate keywords.")
    st.stop()
client = OpenAI(api_key=openai_api_key)
# 🔄 Use OpenAI GPT to assign primary and secondary keywords
def chunk_pages(pages, chunk_size=25):
    for i in range(0, len(pages), chunk_size):
        yield pages[i:i+chunk_size]
# Prepare page:queries dict
page_queries = {}
for page, group in top_queries.groupby("page"):
    queries = group.sort_values(by=["clicks", "impressions"], ascending=False)["query"].head(5).tolist()
    page_queries[page] = queries
gpt_results = []
for i, chunk in enumerate(chunk_pages(list(page_queries.items()))):
    prompt = "You are an SEO assistant. For each page below, return the best primary keyword (highest clicks) and a different secondary keyword (highest impressions).\n\n"
    for page, queries in chunk:
        prompt += f"Page: {page}\nTop Queries: {', '.join(queries)}\n\n"
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        gpt_results.append(response.choices[0].message.content.strip())
    except Exception as e:
        st.error(f"❌ GPT error in chunk {i+1}: {e}")
        continue
# Parse GPT result into DataFrame
keyword_rows = []
for chunk in gpt_results:
    for line in chunk.split("\n"):
        if line.strip().startswith("Page:"):
            page = line.replace("Page:", "").strip()
        elif line.strip().startswith("Primary:"):
            primary = line.replace("Primary:", "").strip()
        elif line.strip().startswith("Secondary:"):
            secondary = line.replace("Secondary:", "").strip()
            keyword_rows.append({"page": page, "primary_keyword": primary, "secondary_keyword": secondary})
df_keywords = pd.DataFrame(keyword_rows)
for page, group in top_queries.groupby("page"):
    group_sorted = group.sort_values(by=["clicks", "impressions"], ascending=False)
    primary = group_sorted.iloc[0]["query"] if not group_sorted.empty else ""
    secondary = ""
    for _, row in group_sorted.iterrows():
        if row["query"] != primary:
            secondary = row["query"]
            break
    keyword_rows.append({
        "page": page,
        "primary_keyword": primary,
        "secondary_keyword": secondary,
    })
df_keywords = pd.DataFrame(keyword_rows)
st.subheader("📋 Primary & Secondary Keywords")
st.dataframe(df_keywords)
csv = df_keywords.to_csv(index=False)
st.download_button("📥 Download CSV", csv, "keywords.csv", "text/csv")
