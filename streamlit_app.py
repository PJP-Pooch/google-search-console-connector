# streamlit_app.py — Combined Charly's GSC Connector with Meta Generator

import streamlit as st
import pandas as pd
import openai
import searchconsole
from google_auth_oauthlib.flow import Flow
from apiclient import discovery

# === UI Setup ===
st.set_page_config(layout="wide", page_title="GSC Meta Generator", page_icon="🔍")
st.title("🔍 GSC Meta Title & Description Generator")

# === OpenAI Key Input ===
openai_api_key = st.sidebar.text_input("🔑 Enter your OpenAI API Key", type="password")
if not openai_api_key:
    st.stop()
openai.api_key = openai_api_key

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

# === Google Sign-In ===
if "my_token_input" not in st.session_state:
    st.markdown(f"[🔐 Sign in with Google]({auth_url})", unsafe_allow_html=True)
    code = st.experimental_get_query_params().get("code")
    if code:
        st.session_state.my_token_input = code[0]

if "my_token_input" in st.session_state:
    flow.fetch_token(code=st.session_state.my_token_input)
    credentials = flow.credentials
    service = discovery.build("webmasters", "v3", credentials=credentials)
    account = searchconsole.account.Account(service, credentials)

    site_list = service.sites().list().execute()
    site_urls = [site["siteUrl"] for site in site_list["siteEntry"]]
    selected_site = st.selectbox("🌐 Select GSC Property", site_urls)

    if selected_site:
        webproperty = account[selected_site]

        # === Date Selection ===
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date")
        with col2:
            end_date = st.date_input("End Date")

        # === Pull Data ===
        if st.button("📊 Fetch GSC Data"):
            with st.spinner("Getting data from Google Search Console..."):
                df = (
                    webproperty.query.range(str(start_date), str(end_date))
                    .dimension("page", "query")
                    .get()
                    .to_dataframe()
                )

                if df.empty:
                    st.warning("No data returned. Please adjust your filters.")
                    st.stop()

                st.subheader("🔍 Raw GSC Data")
                st.dataframe(df.head())

                # === Meta Generation Logic ===
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

                # === Show Output ===
                st.subheader("📝 AI-Generated Meta Tags")
                st.dataframe(top_queries)

                csv = top_queries.to_csv(index=False)
                st.download_button("📥 Download CSV", csv, "meta_tags.csv", "text/csv")
else:
    st.info("Please sign in with Google to continue.")
