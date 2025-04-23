
import streamlit as st
import pandas as pd
import searchconsole
from google_auth_oauthlib.flow import Flow
from apiclient.discovery import build

st.set_page_config(page_title="GSC Keyword Extractor", layout="wide")
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
        st.success("✅ Google authentication successful!")
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

    page_filter_value = st.sidebar.text_input("Filter Pages (contains)", "/products")
    query_filter_value = st.sidebar.text_input("Exclude Queries Containing", "pooch")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date")
    with col2:
        end_date = st.date_input("End Date")

    if st.button("📊 Fetch and Generate Keywords"):
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
            st.warning("No data returned. Adjust your filters.")
            st.stop()

        top_queries = (
            df.groupby("page")
            .apply(lambda g: g.sort_values(by=["clicks", "impressions"], ascending=False).head(10))
            .reset_index(drop=True)
        )

        st.subheader("🔍 Preview: Top Queries by Page")
        st.dataframe(top_queries.head(50))

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

        def highlight_brand(val):
            return "background-color: #ffe0e0" if isinstance(val, str) and "pooch" in val.lower() else ""

        styled_df = df_keywords.style.applymap(highlight_brand, subset=["primary_keyword", "secondary_keyword"])

        st.subheader("📋 Primary & Secondary Keywords")
        st.dataframe(styled_df)

        csv = df_keywords.to_csv(index=False)
        st.download_button("📥 Download CSV", csv, "keywords.csv", "text/csv")
