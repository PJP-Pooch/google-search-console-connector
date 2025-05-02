import streamlit as st
import pandas as pd
import searchconsole
from google_auth_oauthlib.flow import Flow
from apiclient.discovery import build
import openai
from openai import OpenAI
import re

# Initialize session state for filters
if "page_filter_value" not in st.session_state:
    st.session_state["page_filter_value"] = ""
if "query_filter_value" not in st.session_state:
    st.session_state["query_filter_value"] = ""

st.set_page_config(page_title="GSC Keyword Extractor", layout="wide")


def safe_regex_match(series, pattern, invert=False):
    try:
        matched = series.str.match(pattern)
        return ~matched if invert else matched
    except re.error:
        return pd.Series([False] * len(series))

def apply_page_filter(df, filter_type, filter_values):
    if not filter_values:
        return df
    if filter_type == "contains":
        return df[df["page"].str.contains('|'.join(map(re.escape, filter_values)), case=False, na=False)]
    elif filter_type == "starts with":
        return df[df["page"].str.startswith(tuple(filter_values))]
    elif filter_type == "ends with":
        return df[df["page"].str.endswith(tuple(filter_values))]
    elif filter_type == "regex match":
        return df[safe_regex_match(df["page"], '|'.join(filter_values))]
    elif filter_type == "doesn't match regex":
        return df[safe_regex_match(df["page"], '|'.join(filter_values), invert=True)]
    return df

def apply_query_filter(df, filter_type, filter_values):
    if not filter_values:
        return df
    if filter_type == "contains":
        return df[df["query"].str.contains('|'.join(map(re.escape, filter_values)), case=False, na=False)]
    elif filter_type == "starts with":
        return df[df["query"].str.startswith(tuple(filter_values))]
    elif filter_type == "ends with":
        return df[df["query"].str.endswith(tuple(filter_values))]
    elif filter_type == "regex match":
        return df[safe_regex_match(df["query"], '|'.join(filter_values))]
    elif filter_type == "doesn't match regex":
        return df[safe_regex_match(df["query"], '|'.join(filter_values), invert=True)]
    return df


def chunk_dict(d, size):
    items = list(d.items())
    for i in range(0, len(items), size):
        yield dict(items[i:i + size])

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

# ✅ Advanced Page Filter Options
st.sidebar.markdown("### 🔍 Page Filter")

# 🔄 Optional Reset Filters Button
if st.sidebar.button("🔁 Reset Filters"):
    st.session_state["page_filter_value"] = ""
    st.session_state["query_filter_value"] = ""

page_filter_value = st.sidebar.text_input("Page filter value(s) (comma-separated)", st.session_state["page_filter_value"])
query_filter_value = st.sidebar.text_input("Query filter value(s) (comma-separated)", st.session_state["query_filter_value"])

page_filter_values = [v.strip() for v in page_filter_value.split(",") if v.strip()]
query_filter_values = [v.strip() for v in query_filter_value.split(",") if v.strip()]

if "account" in st.session_state:
    def get_sites(account):
        return account.service.sites().list().execute()
    
    site_list = get_sites(st.session_state["account"])
    site_urls = [site["siteUrl"] for site in site_list["siteEntry"]]
    selected_site = st.selectbox("🌐 Select GSC Property", site_urls)
    
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
    
    if st.button("📊 Fetch GSC Data"):
        with st.spinner("Fetching from Google Search Console..."):
            webproperty = st.session_state["account"][selected_site]
    
            df = (
                webproperty.query.range("today", days=days)
                .dimension("page", "query")
                .get()
                .to_dataframe()
            )
    
            # ✅ Make sure these come BEFORE the filter functions
            page_filter_values = [v.strip() for v in page_filter_value.split(",") if v.strip()]
            query_filter_values = [v.strip() for v in query_filter_value.split(",") if v.strip()]
    
            # Apply filters
            df = apply_page_filter(df, page_filter_type, page_filter_values)
            df = apply_query_filter(df, query_filter_type, query_filter_values)


            
            if df.empty:
                st.warning("No data returned. Adjust your filters.")
                st.stop()
                
            st.session_state["gsc_data"] = df
            st.success("✅ GSC data fetched!")
            st.dataframe(df.head(50))
    
    if "gsc_data" in st.session_state:
        st.markdown("### Step 2: Generate Keywords with OpenAI")
        
        # 🔑 Require OpenAI API Key only after GSC data is ready
        openai_api_key = st.sidebar.text_input("Enter your OpenAI API Key", type="password")
        
        if st.button("✨ Run Keyword Selection"):
            if not openai_api_key:
                st.warning("Please enter your OpenAI API Key to generate keywords.")
                st.stop()
                
            with st.spinner("Generating keywords using OpenAI..."):
                client = OpenAI(api_key=openai_api_key)
                df = st.session_state["gsc_data"]
                
                top_queries = (
                    df.groupby("page")
                    .apply(lambda g: g.sort_values(by=["clicks", "impressions"], ascending=False).head(5))
                    .reset_index(drop=True)
                )
                
                # Prepare page:queries dict
                page_queries = {}
                for _, row in top_queries.iterrows():
                    if row["page"] not in page_queries:
                        page_queries[row["page"]] = []
                    page_queries[row["page"]].append(row["query"])
                
                keyword_rows = []
                for chunk in chunk_dict(page_queries, 25):
                    prompt = "You are an SEO expert. For each page below, choose the best primary keyword (the one with highest clicks) and a secondary keyword (a different one with the highest impressions).\n\n"
                    for page, queries in chunk.items():
                        prompt += f"Page: {page}\nTop Queries: {', '.join(queries)}\n\n"
                    
                    try:
                        response = client.chat.completions.create(
                            model="gpt-3.5-turbo",
                            messages=[{"role": "user", "content": prompt}]
                        )
                        result = response.choices[0].message.content.strip()
                        
                        current_page = None
                        primary = None
                        secondary = None
                        
                        for line in result.split("\n"):
                            if line.strip().startswith("Page:"):
                                # Save previous entry if we have one
                                if current_page and primary and secondary:
                                    keyword_rows.append({
                                        "page": current_page, 
                                        "primary_keyword": primary, 
                                        "secondary_keyword": secondary
                                    })
                                
                                current_page = line.replace("Page:", "").strip()
                                primary = None
                                secondary = None
                            elif line.strip().startswith("Primary:"):
                                primary = line.replace("Primary:", "").strip()
                            elif line.strip().startswith("Secondary:"):
                                secondary = line.replace("Secondary:", "").strip()
                                
                                # Save entry if we have a complete set
                                if current_page and primary and secondary:
                                    keyword_rows.append({
                                        "page": current_page, 
                                        "primary_keyword": primary, 
                                        "secondary_keyword": secondary
                                    })
                                    
                                    # Reset for next entry
                                    current_page = None
                                    primary = None
                                    secondary = None
                    except Exception as e:
                        st.error(f"❌ GPT error in chunk: {e}")
                        continue
                
                df_keywords = pd.DataFrame(keyword_rows)
                
                st.subheader("📋 Primary & Secondary Keywords")
                st.dataframe(df_keywords)
                
                csv = df_keywords.to_csv(index=False)
                st.download_button("📥 Download CSV", csv, "keywords.csv", "text/csv")
