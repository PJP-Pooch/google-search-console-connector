
import streamlit as st
import pandas as pd
import searchconsole
from google_auth_oauthlib.flow import Flow
from apiclient import discovery

# Setup
st.set_page_config(page_title="GSC Keyword Extractor", layout="wide")
st.title("🔍 GSC Primary & Secondary Keyword Generator")

# OAuth setup (assumes secrets configured)
client_id = st.secrets["installed"]["client_id"]
client_secret = st.secrets["installed"]["client_secret"]
redirect_uri = st.secrets["installed"]["redirect_uris"][0]

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

query_params = st.query_params
code = query_params.get("code", [None])[0]

if code and "account" not in st.session_state:
    try:
        flow.fetch_token(code=code)
        credentials = flow.credentials
        service = discovery.build("webmasters", "v3", credentials=credentials)
        account = searchconsole.account.Account(service, credentials)
        st.session_state["account"] = account
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error("❌ Google auth failed.")
        st.exception(e)
        st.stop()

if "account" not in st.session_state:
    st.markdown(f"[🔐 Connect to Google Search Console]({auth_url})", unsafe_allow_html=True)
    st.stop()

account = st.session_state["account"]
site_list = account.service.sites().list().execute()
site_urls = [site["siteUrl"] for site in site_list["siteEntry"]]
selected_site = st.selectbox("🌐 Select GSC Property", site_urls)

# Filter and date settings
page_filter_value = st.sidebar.text_input("Filter Pages (contains)", "/products")
query_filter_value = st.sidebar.text_input("Exclude Queries Containing", "pooch")

col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Start Date")
with col2:
    end_date = st.date_input("End Date")

# Fetch GSC Data
with st.spinner("Fetching data from GSC..."):
    webproperty = account[selected_site]
    df = (
        webproperty.query.range(str(start_date), str(end_date))
        .dimension("page", "query")
        .get()
        .to_dataframe()
    )

    if page_filter_value:
        df = df[df["page"].str.contains(page_filter_value, case=False, na=False)]
    if query_filter_value:
        df = df[~df["query"].str.contains(query_filter_value, case=False, na=False)]

    if df.empty:
        st.warning("No data returned with these filters.")
        st.stop()

# Top queries preview
st.subheader("🔍 Preview: Top Queries by Page")
top_queries = (
    df.groupby("page")
    .apply(lambda g: g.sort_values(by=["clicks", "impressions"], ascending=False).head(10))
    .reset_index(drop=True)
)
st.dataframe(top_queries.head(50))

# Extract primary/secondary keywords
keyword_rows = []
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

# Highlight branded
def highlight_brand(val):
    return "background-color: #ffe0e0" if isinstance(val, str) and "pooch" in val.lower() else ""

styled_df = df_keywords.style.applymap(highlight_brand, subset=["primary_keyword", "secondary_keyword"])

st.subheader("📋 Primary & Secondary Keywords")
st.dataframe(styled_df)

csv = df_keywords.to_csv(index=False)
st.download_button("📥 Download CSV", csv, "keywords.csv", "text/csv")
