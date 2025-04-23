
import streamlit as st
import pandas as pd
from openai import OpenAI
import searchconsole
from google_auth_oauthlib.flow import Flow
from apiclient import discovery
from datetime import datetime, timedelta
import re

st.set_page_config(layout="wide", page_title="GSC AI Meta Generator", page_icon="🧠")
st.title("🧠 GSC: Keywords + Meta Tags + Advanced Filters")

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


meta_model = st.sidebar.selectbox("🤖 Meta Generation Model", ["gpt-4", "gpt-3.5-turbo"], index=0)

# === GSC Property and Date Selection
account = st.session_state["account"]
site_list = account.service.sites().list().execute()
site_urls = [site["siteUrl"] for site in site_list["siteEntry"]]
selected_site = st.selectbox("Select GSC Property", site_urls)

date_range = st.selectbox("Date range", ["Last 7 days", "Last 28 days", "Last 3 months"], index=1)
days_map = {"Last 7 days": 7, "Last 28 days": 28, "Last 3 months": 91}
start_date = datetime.today() - timedelta(days=days_map[date_range])
end_date = datetime.today()

with st.expander("🔍 Optional Filters", expanded=False):

# === Page filters
    page_filter_type = st.selectbox("Page Filter Type", ["None", "Contains", "Starts with", "Ends with", "Regex match"])
    page_filter_value = st.text_input("Page Filter Value")

# === Query exclusion
    query_exclude_type = st.selectbox("Exclude Queries That", ["None", "Contains", "Regex match", "Doesn't match"])
    query_exclude_value = st.text_input("Query Exclusion Value")

# === Fetch and Generate
if st.button("📊 Fetch and Generate Keywords & Meta"):
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

        # === Apply page-level filter
        if page_filter_type != "None" and page_filter_value:
            if page_filter_type == "Contains":
                df = df[df["page"].str.contains(page_filter_value)]
            elif page_filter_type == "Starts with":
                df = df[df["page"].str.startswith(page_filter_value)]
            elif page_filter_type == "Ends with":
                df = df[df["page"].str.endswith(page_filter_value)]
            elif page_filter_type == "Regex match":
                df = df[df["page"].str.contains(page_filter_value, regex=True)]

        # === Apply query exclusion
        if query_exclude_type != "None" and query_exclude_value:
            if query_exclude_type == "Contains":
                df = df[~df["query"].str.contains(query_exclude_value)]
            elif query_exclude_type == "Regex match":
                df = df[~df["query"].str.contains(query_exclude_value, regex=True)]
            elif query_exclude_type == "Doesn't match":
                df = df[df["query"].str.contains(query_exclude_value, regex=True)]

        top_pages = df.groupby("page").agg({"clicks": "sum"}).reset_index()
        top_100_pages = top_pages.sort_values("clicks", ascending=False).head(100)["page"]
        df_filtered = df[df["page"].isin(top_100_pages)].copy()

    st.success("✅ GSC data fetched. Generating primary and secondary keywords...")

    # === Keyword Generation
    pages = list(df_filtered["page"].unique())
    chunks = [pages[i:i + 25] for i in range(0, len(pages), 25)]
    keyword_rows = []

    for i, chunk in enumerate(chunks):
        chunk_df = df_filtered[df_filtered["page"].isin(chunk)]
        prompt = (
            "You are an SEO assistant. For each page below, return the best primary keyword (highest clicks) "
            "and a different secondary keyword (highest impressions).\n\n"
        )
        for page, group in chunk_df.groupby("page"):
            top_queries = group.sort_values(by=["clicks", "impressions"], ascending=False).head(5)
            query_text = top_queries[["query", "clicks", "impressions"]].to_string(index=False)
            prompt += (
    f"Page: {page}\n"
    f"{query_text}\n"
    "Primary: \n"
    "Secondary: \n\n"
)

        with st.spinner(f"🔍 Generating keywords for chunk {i+1}/{len(chunks)}..."):
            try:
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}]
                )
                result = response.choices[0].message.content.strip()
            except Exception as e:
                st.error(f"❌ Error in chunk {i+1}: {e}")
                continue

        for block in result.split("Page: ")[1:]:
            lines = block.strip().splitlines()
            page = lines[0].strip()
            primary = secondary = ""
            for line in lines:
                if line.lower().startswith("primary:"):
                    primary = line.split(":", 1)[1].strip()
                elif line.lower().startswith("secondary:"):
                    secondary = line.split(":", 1)[1].strip()
            keyword_rows.append({"page": page, "primary_keyword": primary, "secondary_keyword": secondary})

    df_keywords = pd.DataFrame(keyword_rows)
    st.success("✅ Keywords generated. Generating meta titles and descriptions...")

    # === Meta Title & Description Generation (chunked)
    meta_rows = []
    chunks = [df_keywords.iloc[i:i + 5] for i in range(0, len(df_keywords), 10)]

    for i, chunk in enumerate(chunks):
        meta_prompt = "For each page and keywords below, generate a meta title under 70 characters ending with '| Pooch & Mutt', and a meta description under 160 characters including both keywords and a CTA.

"
        for _, row in chunk.iterrows():
            meta_prompt += (
                f"Page: {row['page']}
"
                f"Primary: {row['primary_keyword']}
"
                f"Secondary: {row['secondary_keyword']}
"
                f"Title: 
"
                f"Description: 

"
            )

        with st.spinner(f\"✍️ Generating meta content for chunk {i+1}/{len(chunks)}...\"):
            try:
                response = client.chat.completions.create(
                    model=meta_model,
                    messages=[{\"role\": \"user\", \"content\": meta_prompt}]
                )
                result = response.choices[0].message.content.strip()
            except Exception as e:
                st.warning(f\"Retrying due to error in meta chunk {i+1}...\")
                try:
                    time.sleep(5)
                    response = client.chat.completions.create(
                        model=meta_model,
                        messages=[{\"role\": \"user\", \"content\": meta_prompt}]
                    )
                    result = response.choices[0].message.content.strip()
                except Exception as e2:
                    st.error(f\"❌ Final failure in meta chunk {i+1}: {e2}\")
                    continue
            except Exception as e:
                st.error(f"❌ Error in meta chunk {i+1}: {e}")
                continue

        for block in result.split("Page: ")[1:]:
            lines = block.strip().splitlines()
            page = lines[0].strip()
            title = description = ""
            for line in lines:
                if line.lower().startswith("title:"):
                    title = line.split(":", 1)[1].strip()
                elif line.lower().startswith("description:"):
                    description = line.split(":", 1)[1].strip()
            meta_rows.append({
                "page": page,
                "meta_title": title,
                "meta_description": description
            })

    df_meta = pd.DataFrame(meta_rows)
    final_df = pd.merge(df_keywords, df_meta, on="page", how="left")

    st.subheader("📝 Preview Meta Titles & Descriptions")
    st.dataframe(final_df)

    st.download_button("📥 Download CSV", final_df.to_csv(index=False), "meta_keywords_output.csv", "text/csv")
