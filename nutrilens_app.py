"""
NutriLens - Open Food Facts Dashboard (Fixed & Streamlined)

Features:
- Search products by keyword/country/category
- Average nutrients and NutriScore/EcoScore summaries
- Top brands analysis
- Top ingredients frequency
- Product barcode lookup

Requirements:
pip install streamlit pandas requests plotly

Run:
streamlit run nutrilens_app.py
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from collections import Counter
from typing import List, Dict
import math

st.set_page_config(page_title="NutriLens", layout="wide", initial_sidebar_state="expanded")

API_SEARCH_BASE = "https://world.openfoodfacts.org/cgi/search.pl"
API_PRODUCT_BASE = "https://world.openfoodfacts.org/api/v0/product/{barcode}.json"

# ---------------------
# Utility functions
# ---------------------
@st.cache_data(ttl=60*30)
def fetch_products(search_terms: str = "", country: str = "", category: str = "", page_size: int = 100, page: int = 1) -> Dict:
    """Query Open Food Facts API and return results"""
    page_size = min(page_size, 100)
    params = {
        "search_terms": search_terms,
        "search_simple": 1,
        "action": "process",
        "json": 1,
        "page_size": page_size,
        "page": page
    }
    if country:
        params["countries"] = country
    if category:
        params["tagtype_0"] = "categories"
        params["tag_contains_0"] = "contains"
        params["tag_0"] = category

    resp = requests.get(API_SEARCH_BASE, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()

@st.cache_data(ttl=60*60)
def fetch_product_by_barcode(barcode: str) -> Dict:
    """Fetch single product by barcode"""
    url = API_PRODUCT_BASE.format(barcode=barcode)
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()

def normalize_products_json(results_json: Dict) -> pd.DataFrame:
    """Convert API response to pandas DataFrame"""
    products = results_json.get("products", [])
    if not products:
        return pd.DataFrame()
    
    rows = []
    for p in products:
        nutr = p.get("nutriments", {}) or {}
        row = {
            "product_name": p.get("product_name") or p.get("generic_name") or "Unknown",
            "brands": p.get("brands") or "Unknown",
            "categories": p.get("categories") or "",
            "countries": p.get("countries") or "",
            "nutriscore": (p.get("nutrition_grade_fr") or p.get("nutrition_grades") or "").lower(),
            "ecoscore": (p.get("ecoscore_grade") or "").lower(),
            "ingredients_text": p.get("ingredients_text") or "",
            "ingredients_tags": p.get("ingredients_tags") or [],
            "barcode": p.get("code") or "",
            "energy_100g_kcal": nutr.get("energy-kcal_100g") or nutr.get("energy_100g"),
            "fat_100g": nutr.get("fat_100g"),
            "saturated_fat_100g": nutr.get("saturated-fat_100g"),
            "carbohydrates_100g": nutr.get("carbohydrates_100g"),
            "sugars_100g": nutr.get("sugars_100g"),
            "fiber_100g": nutr.get("fiber_100g"),
            "proteins_100g": nutr.get("proteins_100g"),
            "salt_100g": nutr.get("salt_100g"),
            "image_url": p.get("image_front_small_url") or p.get("image_url") or "",
        }
        rows.append(row)
    
    return pd.DataFrame(rows)

def top_ingredients_from_df(df: pd.DataFrame, top_n: int = 20) -> List[tuple]:
    """Extract top ingredients from standardized tags"""
    counter = Counter()
    for tags in df["ingredients_tags"].dropna():
        if isinstance(tags, list):
            for t in tags:
                name = t.split(":")[-1].replace("-", " ").title()
                counter[name] += 1
    return counter.most_common(top_n)

def brand_summary(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Summarize top brands with product counts and avg nutriscore"""
    df_br = df[df["brands"] != "Unknown"].copy()
    df_br["primary_brand"] = df_br["brands"].str.split(",").str[0].str.strip()
    
    summary = (df_br.groupby("primary_brand")
               .agg(
                   num_products=("product_name", "count"),
                   avg_nutriscore=("nutriscore", lambda s: nutriscore_to_numeric(s).mean())
               )
               .reset_index()
               .sort_values("num_products", ascending=False)
               .head(top_n))
    
    return summary

def nutriscore_to_numeric(series: pd.Series) -> pd.Series:
    """Convert nutriscore letters to numbers (a=1 best, e=5 worst)"""
    mapping = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
    return series.str.lower().map(mapping)

# ---------------------
# Main UI
# ---------------------
st.title("🥗 NutriLens — Food & Nutrition Insights")
st.markdown("Explore nutrition and eco data from **Open Food Facts**")

# Sidebar controls
with st.sidebar:
    st.header("🔍 Search Products")
    search_term = st.text_input("Keyword", value="chocolate", help="Product name or keyword")
    country = st.text_input("Country (optional)", value="", placeholder="e.g., France, United States")
    category = st.text_input("Category (optional)", value="", placeholder="e.g., biscuits, beverages")
    pagesize = st.slider("Number of products", min_value=10, max_value=100, value=50, step=10)
    run_query = st.button("🔎 Search", type="primary")

    st.markdown("---")
    st.header("📊 Barcode Lookup")
    barcode = st.text_input("Enter barcode", value="", placeholder="e.g., 3017620422003")
    lookup_btn = st.button("🔍 Lookup")

# Initialize session state for data persistence
if "df" not in st.session_state:
    st.session_state.df = None

# Main search flow
if run_query:
    with st.spinner("Fetching products from Open Food Facts..."):
        try:
            results = fetch_products(search_terms=search_term, country=country, category=category, page_size=pagesize)
            df = normalize_products_json(results)
            
            if not df.empty:
                st.session_state.df = df
                st.success(f"✅ Fetched {len(df)} products!")
            else:
                st.warning("No products found. Try different search terms.")
        except Exception as e:
            st.error(f"Error fetching products: {e}")
            st.stop()

# Barcode lookup
# Barcode lookup
if lookup_btn and barcode.strip():
    with st.spinner("Looking up product..."):
        try:
            product_json = fetch_product_by_barcode(barcode.strip())
            
            if product_json.get("status") == 1:
                prod = product_json.get("product", {})
                st.subheader("📦 Product Details")
                
                # Main product info
                col1, col2 = st.columns([1, 3])
                with col1:
                    if prod.get("image_front_small_url") or prod.get("image_url"):
                        st.image(prod.get("image_front_small_url") or prod.get("image_url"), width=150)
                
                with col2:
                    st.markdown(f"### {prod.get('product_name') or prod.get('generic_name') or 'Unknown'}")
                    st.markdown(f"**Brand:** {prod.get('brands') or 'Unknown'}")
                    st.markdown(f"**Barcode:** {prod.get('code') or barcode}")
                    
                    score_col1, score_col2, score_col3 = st.columns(3)
                    with score_col1:
                        nutri = (prod.get('nutrition_grade_fr') or prod.get('nutrition_grades') or 'N/A').upper()
                        st.metric("NutriScore", nutri)
                    with score_col2:
                        eco = (prod.get('ecoscore_grade') or 'N/A').upper()
                        st.metric("EcoScore", eco)
                    with score_col3:
                        nova = prod.get("nutriments", {}).get("nova-group", "N/A")
                        st.metric("NOVA Group", nova)
                
                # Nutrition Facts Card
                st.markdown("#### 📊 Nutrition Facts (per 100g)")
                nutr = prod.get("nutriments", {})
                
                if nutr:
                    ncol1, ncol2, ncol3, ncol4 = st.columns(4)
                    
                    with ncol1:
                        energy_kcal = nutr.get("energy-kcal_100g") or nutr.get("energy_100g", 0)
                        if isinstance(energy_kcal, (int, float)) and energy_kcal > 1000:
                            energy_kcal = energy_kcal / 4.184  # Convert kJ to kcal
                        st.metric("Energy", f"{energy_kcal:.0f} kcal" if energy_kcal else "N/A")
                        
                        fat = nutr.get("fat_100g")
                        st.metric("Fat", f"{fat:.1f}g" if fat else "N/A")
                    
                    with ncol2:
                        carbs = nutr.get("carbohydrates_100g")
                        st.metric("Carbs", f"{carbs:.1f}g" if carbs else "N/A")
                        
                        sugars = nutr.get("sugars_100g")
                        st.metric("- Sugars", f"{sugars:.1f}g" if sugars else "N/A")
                    
                    with ncol3:
                        protein = nutr.get("proteins_100g")
                        st.metric("Protein", f"{protein:.1f}g" if protein else "N/A")
                        
                        fiber = nutr.get("fiber_100g")
                        st.metric("Fiber", f"{fiber:.1f}g" if fiber else "N/A")
                    
                    with ncol4:
                        salt = nutr.get("salt_100g")
                        st.metric("Salt", f"{salt:.2f}g" if salt else "N/A")
                        
                        sat_fat = nutr.get("saturated-fat_100g")
                        st.metric("Sat. Fat", f"{sat_fat:.1f}g" if sat_fat else "N/A")
                
                # Ingredients section
                if prod.get("ingredients_text"):
                    st.markdown("#### 🥕 Ingredients")
                    st.info(prod.get("ingredients_text"))
                
                # Additional info in expanders
                col1, col2 = st.columns(2)
                
                with col1:
                    with st.expander("🔬 Detailed Nutriments"):
                        if nutr:
                            # Create a clean dataframe of nutrients
                            nutrient_data = []
                            for key, value in nutr.items():
                                if isinstance(value, (int, float)) and "_100g" in key:
                                    clean_key = key.replace("_100g", "").replace("-", " ").title()
                                    nutrient_data.append({"Nutrient": clean_key, "Per 100g": f"{value:.2f}"})
                            
                            if nutrient_data:
                                df_nutrients = pd.DataFrame(nutrient_data)
                                st.dataframe(df_nutrients, use_container_width=True, hide_index=True)
                            else:
                                st.json(nutr)
                        else:
                            st.info("No nutrition data available")
                
                with col2:
                    with st.expander("ℹ️ Product Information"):
                        info_data = {
                            "Categories": prod.get("categories", "N/A"),
                            "Countries": prod.get("countries", "N/A"),
                            "Labels": prod.get("labels", "N/A"),
                            "Packaging": prod.get("packaging", "N/A"),
                            "Quantity": prod.get("quantity", "N/A"),
                        }
                        for key, value in info_data.items():
                            if value and value != "N/A":
                                st.markdown(f"**{key}:** {value}")
            else:
                st.error("❌ Product not found in database")
        except Exception as e:
            st.error(f"Error fetching product: {e}")

# Dashboard - only show if data exists
df = st.session_state.df

if df is not None and not df.empty:
    st.markdown("---")
    
    # Overview metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🔢 Total Products", len(df))
    col2.metric("🏷️ Unique Brands", df[df["brands"] != "Unknown"]["brands"].str.split(",").str[0].nunique())
    col3.metric("🌍 Countries", df[df["countries"] != ""]["countries"].nunique())
    col4.metric("📊 With NutriScore", df[df["nutriscore"] != ""].shape[0])

    # Tabs for organized content
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Nutrition", "🏆 Scores", "🏭 Brands", "🥕 Ingredients"])
    
    with tab1:
        st.subheader("Average Nutrients (per 100g)")
        nutrient_cols = ["energy_100g_kcal", "fat_100g", "saturated_fat_100g", 
                        "carbohydrates_100g", "sugars_100g", "fiber_100g", 
                        "proteins_100g", "salt_100g"]
        
        avg_series = df[nutrient_cols].mean(skipna=True)
        avg_df = avg_series.reset_index()
        avg_df.columns = ["Nutrient", "Average per 100g"]
        avg_df = avg_df.dropna()
        
        if not avg_df.empty:
            fig = px.bar(avg_df, x="Nutrient", y="Average per 100g", 
                        title="Average Nutritional Values", 
                        color="Average per 100g",
                        color_continuous_scale="Viridis")
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No nutrition data available")
    
    with tab2:
        st.subheader("NutriScore & EcoScore Distribution")
        
        col1, col2 = st.columns(2)
        
        with col1:
            nutri_data = df[df["nutriscore"] != ""]["nutriscore"].str.upper().value_counts()
            if not nutri_data.empty:
                fig = px.pie(values=nutri_data.values, names=nutri_data.index, 
                           title="NutriScore Distribution",
                           color=nutri_data.index,
                           color_discrete_map={"A": "darkgreen", "B": "lightgreen", 
                                              "C": "yellow", "D": "orange", "E": "red"})
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No NutriScore data available")
        
        with col2:
            eco_data = df[df["ecoscore"] != ""]["ecoscore"].str.upper().value_counts()
            if not eco_data.empty:
                fig = px.pie(values=eco_data.values, names=eco_data.index,
                           title="EcoScore Distribution")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No EcoScore data available")
    
    with tab3:
        st.subheader("Top Brands Analysis")
        br_summary = brand_summary(df, top_n=12)
        
        if not br_summary.empty:
            fig = px.bar(br_summary, x="primary_brand", y="num_products",
                        hover_data=["avg_nutriscore"],
                        title="Top Brands by Product Count",
                        labels={"primary_brand": "Brand", "num_products": "Number of Products"},
                        color="avg_nutriscore",
                        color_continuous_scale="RdYlGn_r")
            fig.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
            
            st.dataframe(br_summary.rename(columns={
                "primary_brand": "Brand",
                "num_products": "Products",
                "avg_nutriscore": "Avg NutriScore (1=best, 5=worst)"
            }), use_container_width=True)
        else:
            st.info("Not enough brand data available")
    
    with tab4:
        st.subheader("Most Common Ingredients")
        top_ing = top_ingredients_from_df(df, top_n=25)
        
        if top_ing:
            ing_df = pd.DataFrame(top_ing, columns=["Ingredient", "Count"])
            fig = px.bar(ing_df.head(15), x="Ingredient", y="Count",
                        title="Top 15 Ingredients",
                        color="Count",
                        color_continuous_scale="Blues")
            fig.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
            
            with st.expander("View full ingredient list"):
                st.dataframe(ing_df, use_container_width=True)
        else:
            st.info("No ingredient data available")
    
    # Product browser
    st.markdown("---")
    st.subheader("🔍 Browse Products")
    
    # Filter options
    col1, col2 = st.columns(2)
    with col1:
        filter_nutri = st.multiselect("Filter by NutriScore", 
                                     options=["A", "B", "C", "D", "E"],
                                     default=[])
    with col2:
        filter_brand = st.selectbox("Filter by Brand", 
                                   options=["All"] + sorted(df[df["brands"] != "Unknown"]["brands"].str.split(",").str[0].unique().tolist()))
    
    # Apply filters
    df_filtered = df.copy()
    if filter_nutri:
        df_filtered = df_filtered[df_filtered["nutriscore"].str.upper().isin(filter_nutri)]
    if filter_brand != "All":
        df_filtered = df_filtered[df_filtered["brands"].str.contains(filter_brand, case=False, na=False)]
    
    # Display filtered results
    st.dataframe(
        df_filtered[["product_name", "brands", "nutriscore", "ecoscore", "energy_100g_kcal", "barcode"]].head(50),
        use_container_width=True,
        column_config={
            "product_name": "Product",
            "brands": "Brand",
            "nutriscore": "NutriScore",
            "ecoscore": "EcoScore",
            "energy_100g_kcal": "Energy (kcal/100g)",
            "barcode": "Barcode"
        }
    )
    
    st.caption(f"Showing {min(50, len(df_filtered))} of {len(df_filtered)} products")
    
    # Extended Dashboard Analytics
    st.markdown("---")
    st.header("📈 Extended Analytics Dashboard")
    
    # Row 1: Nutrient Distributions
    st.subheader("Nutrient Distribution Analysis")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if df["sugars_100g"].notna().sum() > 0:
            fig = px.histogram(df.dropna(subset=["sugars_100g"]), x="sugars_100g", 
                             nbins=30, title="Sugar Content Distribution (per 100g)",
                             labels={"sugars_100g": "Sugars (g)"})
            fig.update_traces(marker_color='#FF6B6B')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No sugar data available")
    
    with col2:
        if df["proteins_100g"].notna().sum() > 0:
            fig = px.histogram(df.dropna(subset=["proteins_100g"]), x="proteins_100g",
                             nbins=30, title="Protein Content Distribution (per 100g)",
                             labels={"proteins_100g": "Protein (g)"})
            fig.update_traces(marker_color='#4ECDC4')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No protein data available")
    
    with col3:
        if df["fat_100g"].notna().sum() > 0:
            fig = px.histogram(df.dropna(subset=["fat_100g"]), x="fat_100g",
                             nbins=30, title="Fat Content Distribution (per 100g)",
                             labels={"fat_100g": "Fat (g)"})
            fig.update_traces(marker_color='#FFE66D')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No fat data available")
    
    # Row 2: Comparative Analysis
    st.subheader("Comparative Nutrient Analysis")
    col1, col2 = st.columns(2)
    
    with col1:
        # Scatter: Energy vs Sugar
        scatter_df = df.dropna(subset=["energy_100g_kcal", "sugars_100g"])
        if not scatter_df.empty:
            fig = px.scatter(scatter_df, x="sugars_100g", y="energy_100g_kcal",
                           color="nutriscore", 
                           title="Energy vs Sugar Content",
                           labels={"sugars_100g": "Sugars (g/100g)", 
                                  "energy_100g_kcal": "Energy (kcal/100g)"},
                           color_discrete_map={"a": "darkgreen", "b": "lightgreen", 
                                              "c": "yellow", "d": "orange", "e": "red"},
                           hover_data=["product_name", "brands"])
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Insufficient data for energy vs sugar analysis")
    
    with col2:
        # Scatter: Protein vs Fat
        scatter_df2 = df.dropna(subset=["proteins_100g", "fat_100g"])
        if not scatter_df2.empty:
            fig = px.scatter(scatter_df2, x="proteins_100g", y="fat_100g",
                           color="nutriscore",
                           title="Protein vs Fat Content",
                           labels={"proteins_100g": "Protein (g/100g)", 
                                  "fat_100g": "Fat (g/100g)"},
                           color_discrete_map={"a": "darkgreen", "b": "lightgreen", 
                                              "c": "yellow", "d": "orange", "e": "red"},
                           hover_data=["product_name", "brands"])
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Insufficient data for protein vs fat analysis")
    
    
    # Row 4: Brand comparison
    st.subheader("Brand Comparison Dashboard")
    
    # Get top brands for detailed comparison
    top_brands_list = df[df["brands"] != "Unknown"]["brands"].str.split(",").str[0].str.strip().value_counts().head(8).index.tolist()
    brand_comp_df = df[df["brands"].str.split(",").str[0].str.strip().isin(top_brands_list)].copy()
    brand_comp_df["primary_brand"] = brand_comp_df["brands"].str.split(",").str[0].str.strip()
    
    if not brand_comp_df.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            # Average nutrients by brand
            nutrient_by_brand = brand_comp_df.groupby("primary_brand")[["energy_100g_kcal", "sugars_100g", "fat_100g", "proteins_100g"]].mean().reset_index()
            nutrient_melted = nutrient_by_brand.melt(id_vars="primary_brand", 
                                                     var_name="Nutrient", 
                                                     value_name="Average")
            fig = px.bar(nutrient_melted, x="primary_brand", y="Average", 
                        color="Nutrient", barmode="group",
                        title="Average Nutrients by Top Brands",
                        labels={"primary_brand": "Brand", "Average": "Per 100g"})
            fig.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # NutriScore distribution by brand
            nutri_by_brand = brand_comp_df.dropna(subset=["nutriscore"]).groupby(["primary_brand", "nutriscore"]).size().reset_index(name="count")
            fig = px.bar(nutri_by_brand, x="primary_brand", y="count", 
                        color="nutriscore", 
                        title="NutriScore Distribution by Brand",
                        labels={"primary_brand": "Brand", "count": "Number of Products"},
                        color_discrete_map={"a": "darkgreen", "b": "lightgreen", 
                                           "c": "yellow", "d": "orange", "e": "red"})
            fig.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Insufficient brand data for comparison")
    
    # Row 5: Advanced metrics
    st.subheader("Advanced Nutritional Metrics")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Calculate sugar-to-carb ratio
        ratio_df = df.dropna(subset=["sugars_100g", "carbohydrates_100g"])
        ratio_df = ratio_df[ratio_df["carbohydrates_100g"] > 0]
        if not ratio_df.empty:
            ratio_df["sugar_ratio"] = (ratio_df["sugars_100g"] / ratio_df["carbohydrates_100g"]) * 100
            fig = px.histogram(ratio_df, x="sugar_ratio", nbins=30,
                             title="Sugar as % of Carbohydrates",
                             labels={"sugar_ratio": "Sugar Ratio (%)"})
            fig.update_traces(marker_color='#9B59B6')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Insufficient data for sugar ratio")
    
    with col2:
        # Fiber content analysis
        if df["fiber_100g"].notna().sum() > 5:
            fiber_df = df.dropna(subset=["fiber_100g", "nutriscore"])
            fig = px.violin(fiber_df, x="nutriscore", y="fiber_100g",
                          title="Fiber Content by NutriScore",
                          labels={"nutriscore": "NutriScore", "fiber_100g": "Fiber (g/100g)"},
                          color="nutriscore",
                          color_discrete_map={"a": "darkgreen", "b": "lightgreen", 
                                             "c": "yellow", "d": "orange", "e": "red"})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Insufficient fiber data")
    
    with col3:
        # Saturated fat percentage
        sat_df = df.dropna(subset=["saturated_fat_100g", "fat_100g"])
        sat_df = sat_df[sat_df["fat_100g"] > 0]
        if not sat_df.empty:
            sat_df["sat_fat_ratio"] = (sat_df["saturated_fat_100g"] / sat_df["fat_100g"]) * 100
            fig = px.histogram(sat_df, x="sat_fat_ratio", nbins=30,
                             title="Saturated Fat as % of Total Fat",
                             labels={"sat_fat_ratio": "Saturated Fat Ratio (%)"})
            fig.update_traces(marker_color='#E67E22')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Insufficient saturated fat data")
    
    # Row 6: Correlation heatmap
    st.subheader("Nutrient Correlation Matrix")
    corr_cols = ["energy_100g_kcal", "fat_100g", "saturated_fat_100g", 
                 "carbohydrates_100g", "sugars_100g", "fiber_100g", 
                 "proteins_100g", "salt_100g"]
    corr_df = df[corr_cols].dropna()
    
    if len(corr_df) > 10:
        correlation_matrix = corr_df.corr()
        fig = px.imshow(correlation_matrix, 
                       title="Correlation Between Nutrients",
                       labels=dict(color="Correlation"),
                       x=correlation_matrix.columns,
                       y=correlation_matrix.columns,
                       color_continuous_scale="RdBu_r",
                       aspect="auto")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Insufficient data for correlation analysis")
    
    # Row 7: Summary statistics table
    st.subheader("📊 Summary Statistics")
    summary_stats = df[corr_cols].describe().T
    summary_stats = summary_stats[["mean", "std", "min", "50%", "max"]]
    summary_stats.columns = ["Mean", "Std Dev", "Min", "Median", "Max"]
    summary_stats.index.name = "Nutrient"
    st.dataframe(summary_stats.style.background_gradient(cmap="YlOrRd", axis=1).format("{:.2f}"), 
                use_container_width=True)

else:
    st.info("👈 Use the sidebar to search for products or lookup a specific barcode")
    st.markdown("""
    ### How to use NutriLens:
    1. **Search Products**: Enter a keyword, country, or category in the sidebar
    2. **Lookup Barcode**: Enter a specific product barcode for detailed info
    3. **Explore Data**: View nutrition averages, scores, brands, and ingredients
    
    Data source: [Open Food Facts](https://world.openfoodfacts.org/)
    """)

st.markdown("---")
st.caption("💡 Data from Open Food Facts | Coverage varies by product | Some fields may be incomplete")