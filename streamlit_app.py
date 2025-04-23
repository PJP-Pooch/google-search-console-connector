
import streamlit as st
import pandas as pd
import openai
import searchconsole
from google_auth_oauthlib.flow import Flow
from apiclient import discovery

# === UI Setup ===
st.set_page_config(layout="wide", page_title="GSC Meta Generator", page_icon="🔍")
st.title("🔍 GSC Meta Title & Description Generator")

# === Google OAuth Setup ===
client_id = str(st.secrets["installed"]["client_id"])
client_secret = str(st.secrets["installed"]["client_secret"])
redirect_uri = str(st.secrets["installed"]["redirect_uris"][0])

st.write(f"🔧 Using redirect URI: {redirect_uri}")  # Debug log

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

if "manual_auth_code" not in st.session_state:
    st.session_state.manual_auth_code = ""

flow = Flow.from_client_config(
    credentials,
    scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    redirect_uri=redirect_uri,
)
auth_url, _ = flow.authorization_url(prompt="consent")

st.markdown(f"🔗 [Click here to authenticate with Google]({auth_url})")
st.caption("After signing in, you'll be redirected to a broken page. Copy the `code` from the URL and paste it below:")

auth_code = st.text_input("Paste your authorization code here")
submit_code = st.button("Submit Code")

if submit_code and auth_code:
    try:
        flow.fetch_token(code=auth_code)
        credentials = flow.credentials
        service = discovery.build("webmasters", "v3", credentials=credentials)
        account = searchconsole.account.Account(service, credentials)
        st.session_state["account"] = account
        st.success("✅ Successfully authenticated with Google!")
        st.experimental_rerun()
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
selected_site = st.selectbox("🌐 Select GSC Property", site_urls)

# === Date Selection ===
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Start Date")
with col2:
    end_date = st.date_input("End Date")

# === OpenAI Key Input ===
openai_api_key = st.sidebar.text_input("🔑 Enter your OpenAI API Key", type="password")
if not openai_api_key:
    st.warning("Please enter your OpenAI API Key to continue.")
    st.stop()
openai.api_key = openai_api_key

# === Pull GSC Data ===
if st.button("📊 Fetch GSC Data"):
    with st.spinner("Getting data from Google Search Console..."):
        webproperty = account[selected_site]
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
