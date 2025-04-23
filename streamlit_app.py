
import streamlit as st
import pandas as pd
from openai import OpenAI
import searchconsole
from google_auth_oauthlib.flow import Flow
from apiclient import discovery
from datetime import datetime, timedelta

st.set_page_config(layout="wide", page_title="Top Queries + AI Keywords CSV", page_icon="🔍")
st.title("🔍 GSC: Top Queries + AI Primary & Secondary Keywords (Structured Output)")

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

# === OpenAI Key
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

# === Fetch and Generate
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

    st.success("✅ Data fetched. Starting AI keyword generation...")

    # === Chunked OpenAI calls with structured parsing
    pages = list(df_filtered["page"].unique())
    chunks = [pages[i:i + 25] for i in range(0, len(pages), 25)]
    rows = []

    for i, chunk in enumerate(chunks):
        chunk_df = df_filtered[df_filtered["page"].isin(chunk)]
        prompt = """You are an SEO assistant. For each page below, return the best primary keyword (highest clicks) and a different secondary keyword (highest impressions).

"""

        for page, group in chunk_df.groupby("page"):
            top_queries = group.sort_values(by=["clicks", "impressions"], ascending=False).head(5)
            query_text = top_queries[["query", "clicks", "impressions"]].to_string(index=False)
            prompt += f"Page: {page}
{query_text}
Primary: 
Secondary: 

"

        with st.spinner(f"Sending request for chunk {i+1}/{len(chunks)}..."):
            try:
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}]
                )
                result = response.choices[0].message.content.strip()
            except Exception as e:
                result = f"❌ Error in chunk {i+1}: {e}"

        # === Parse results
        for block in result.split("Page: ")[1:]:
            lines = block.strip().splitlines()
            page = lines[0].strip()
            primary = secondary = ""
            for line in lines:
                if line.lower().startswith("primary:"):
                    primary = line.split(":", 1)[1].strip()
                elif line.lower().startswith("secondary:"):
                    secondary = line.split(":", 1)[1].strip()
            rows.append({
                "page": page,
                "primary_keyword": primary,
                "secondary_keyword": secondary
            })

    df_output = pd.DataFrame(rows)
    st.subheader("📋 Structured Keyword Output")
    st.dataframe(df_output)
    st.download_button("📥 Download CSV", df_output.to_csv(index=False), "ai_keywords.csv", "text/csv")
