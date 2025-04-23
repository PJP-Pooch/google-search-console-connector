
import streamlit as st
from datetime import datetime, timedelta

st.markdown("## 📅 Search Parameters")

# === Web property selection
selected_site = st.selectbox("🌐 Select GSC Property", site_urls)

# === Dimensions
col1, col2, col3 = st.columns(3)
with col1:
    dimension = st.selectbox("Dimension", ["query", "page", "date", "device", "country", "searchAppearance"])
with col2:
    nested_dimension = st.selectbox("Nested dimension", ["none", "query", "page", "date", "device", "country", "searchAppearance"])
with col3:
    nested_dimension_2 = st.selectbox("Nested dimension 2", ["none", "query", "page", "date", "device", "country", "searchAppearance"])

# === Search type and date range
col4, col5 = st.columns(2)
with col4:
    search_type = st.selectbox("Search type", ["web", "image", "video", "news", "googleNews"])

with col5:
    date_range = st.selectbox(
        "Date range",
        ["Last 7 days", "Last 28 days", "Last 3 months", "Last 6 months", "Last 12 months", "Last 16 months", "Custom"],
        index=0,
    )

# Convert to date values
if date_range == "Last 7 days":
    start_date = datetime.today() - timedelta(days=7)
    end_date = datetime.today()
elif date_range == "Last 28 days":
    start_date = datetime.today() - timedelta(days=28)
    end_date = datetime.today()
elif date_range == "Last 3 months":
    start_date = datetime.today() - timedelta(days=91)
    end_date = datetime.today()
elif date_range == "Last 6 months":
    start_date = datetime.today() - timedelta(days=182)
    end_date = datetime.today()
elif date_range == "Last 12 months":
    start_date = datetime.today() - timedelta(days=365)
    end_date = datetime.today()
elif date_range == "Last 16 months":
    start_date = datetime.today() - timedelta(days=486)
    end_date = datetime.today()
else:
    col6, col7 = st.columns(2)
    with col6:
        start_date = st.date_input("Start date", datetime.today() - timedelta(days=28))
    with col7:
        end_date = st.date_input("End date", datetime.today())

# === Advanced filters
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
