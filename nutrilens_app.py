"""
NutriLens - Open Food Facts Dashboard (Improved Missing Value Handling)

Features:
- Search products by keyword/country/category
- Average nutrients and NutriScore/EcoScore summaries
- Top brands analysis
- Top ingredients frequency
- Product barcode lookup
- Robust missing value handling

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

    resp = requests.get(API_SEARCH_BASE, params=params, timeout=(5,40))
    resp.raise_for_status()
    return resp.json()

@st.cache_data(ttl=60*60)
def fetch_product_by_barcode(barcode: str) -> Dict:
    """Fetch single product by barcode"""
    url = API_PRODUCT_BASE.format(barcode=barcode)
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()

def clean_text_field(value, default=None):
    """Clean text fields - return None if empty/whitespace"""
    if pd.isna(value) or (isinstance(value, str) and value.strip() == ""):
        return default
    return value

def normalize_products_json(results_json: Dict) -> pd.DataFrame:
    """Convert API response to pandas DataFrame with proper null handling"""
    products = results_json.get("products", [])
    if not products:
        return pd.DataFrame()
    
    rows = []
    for p in products:
        nutr = p.get("nutriments", {}) or {}
        
        # Clean product name
        product_name = clean_text_field(p.get("product_name")) or clean_text_field(p.get("generic_name"))
        
        # Clean brand - only include if actually exists
        brands = clean_text_field(p.get("brands"))
        
        # Clean scores - only include valid grades
        nutriscore = clean_text_field(p.get("nutrition_grade_fr")) or clean_text_field(p.get("nutrition_grades"))
        if nutriscore:
            nutriscore = nutriscore.lower()
            if nutriscore not in ['a', 'b', 'c', 'd', 'e']:
                nutriscore = None
        
        ecoscore = clean_text_field(p.get("ecoscore_grade"))
        if ecoscore:
            ecoscore = ecoscore.lower()
            if ecoscore not in ['a', 'b', 'c', 'd', 'e']:
                ecoscore = None
        
        row = {
            "product_name": product_name,
            "brands": brands,
            "categories": clean_text_field(p.get("categories")),
            "countries": clean_text_field(p.get("countries")),
            "nutriscore": nutriscore,
            "ecoscore": ecoscore,
            "ingredients_text": clean_text_field(p.get("ingredients_text")),
            "ingredients_tags": p.get("ingredients_tags") if p.get("ingredients_tags") else None,
            "barcode": clean_text_field(p.get("code")),
            "energy_100g_kcal": nutr.get("energy-kcal_100g") or nutr.get("energy_100g"),
            "fat_100g": nutr.get("fat_100g"),
            "saturated_fat_100g": nutr.get("saturated-fat_100g"),
            "carbohydrates_100g": nutr.get("carbohydrates_100g"),
            "sugars_100g": nutr.get("sugars_100g"),
            "fiber_100g": nutr.get("fiber_100g"),
            "proteins_100g": nutr.get("proteins_100g"),
            "salt_100g": nutr.get("salt_100g"),
            "image_url": clean_text_field(p.get("image_front_small_url")) or clean_text_field(p.get("image_url")),
        }
        
        # Only add row if it has at least a name or barcode
        if row["product_name"] or row["barcode"]:
            rows.append(row)
    
    df = pd.DataFrame(rows)
    
    # Convert numeric columns and handle outliers
    numeric_cols = ["energy_100g_kcal", "fat_100g", "saturated_fat_100g", 
                    "carbohydrates_100g", "sugars_100g", "fiber_100g", 
                    "proteins_100g", "salt_100g"]
    
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        # Filter out unrealistic values (negative or extreme outliers)
        if col in df.columns:
            df.loc[df[col] < 0, col] = None
            if col == "energy_100g_kcal":
                df.loc[df[col] > 900, col] = None  # Unrealistic for most foods
            elif col in ["fat_100g", "carbohydrates_100g", "proteins_100g"]:
                df.loc[df[col] > 100, col] = None  # Can't exceed 100g per 100g
    
    return df

def top_ingredients_from_df(df: pd.DataFrame, top_n: int = 20) -> List[tuple]:
    """Extract top ingredients from standardized tags - filter out unknowns"""
    counter = Counter()
    for tags in df["ingredients_tags"].dropna():
        if isinstance(tags, list) and tags:  # Check list is not empty
            for t in tags:
                name = t.split(":")[-1].replace("-", " ").title()
                # Filter out generic/unknown terms
                if name and name.lower() not in ['unknown', 'n/a', 'none', '']:
                    counter[name] += 1
    return counter.most_common(top_n)

def brand_summary(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Summarize top brands - exclude unknowns and empty values"""
    # Filter out rows with no brand info
    df_br = df[df["brands"].notna()].copy()
    
    if df_br.empty:
        return pd.DataFrame()
    
    df_br["primary_brand"] = df_br["brands"].str.split(",").str[0].str.strip()
    
    # Remove empty brands after processing
    df_br = df_br[df_br["primary_brand"].str.len() > 0]
    
    if df_br.empty:
        return pd.DataFrame()
    
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
                
                # Data quality summary
                total = len(df)
                with_nutri = df["nutriscore"].notna().sum()
                with_eco = df["ecoscore"].notna().sum()
                with_nutrients = df[["energy_100g_kcal", "fat_100g", "proteins_100g"]].notna().any(axis=1).sum()
                
                st.success(f"✅ Fetched {total} products!")
                st.info(f"📊 Data completeness: {with_nutri}/{total} NutriScore | {with_eco}/{total} EcoScore | {with_nutrients}/{total} Nutrients")
            else:
                st.warning("No products found. Try different search terms.")
        except Exception as e:
            st.error(f"Error fetching products: {e}")
            st.stop()

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
                    img_url = prod.get("image_front_small_url") or prod.get("image_url")
                    if img_url:
                        st.image(img_url, width=150)
                
                with col2:
                    product_name = prod.get('product_name') or prod.get('generic_name') or 'Unknown Product'
                    st.markdown(f"### {product_name}")
                    
                    brand = prod.get('brands')
                    st.markdown(f"**Brand:** {brand if brand else 'Not specified'}")
                    st.markdown(f"**Barcode:** {prod.get('code') or barcode}")
                    
                    score_col1, score_col2, score_col3 = st.columns(3)
                    with score_col1:
                        nutri = prod.get('nutrition_grade_fr') or prod.get('nutrition_grades')
                        st.metric("NutriScore", nutri.upper() if nutri else 'N/A')
                    with score_col2:
                        eco = prod.get('ecoscore_grade')
                        st.metric("EcoScore", eco.upper() if eco else 'N/A')
                    with score_col3:
                        nova = prod.get("nutriments", {}).get("nova-group")
                        st.metric("NOVA Group", nova if nova else 'N/A')
                
                # Nutrition Facts Card
                st.markdown("#### 📊 Nutrition Facts (per 100g)")
                nutr = prod.get("nutriments", {})
                
                if nutr:
                    ncol1, ncol2, ncol3, ncol4 = st.columns(4)
                    
                    with ncol1:
                        energy_kcal = nutr.get("energy-kcal_100g") or nutr.get("energy_100g")
                        if energy_kcal and isinstance(energy_kcal, (int, float)) and energy_kcal > 1000:
                            energy_kcal = energy_kcal / 4.184
                        st.metric("Energy", f"{energy_kcal:.0f} kcal" if energy_kcal else "N/A")
                        
                        fat = nutr.get("fat_100g")
                        st.metric("Fat", f"{fat:.1f}g" if fat is not None else "N/A")
                    
                    with ncol2:
                        carbs = nutr.get("carbohydrates_100g")
                        st.metric("Carbs", f"{carbs:.1f}g" if carbs is not None else "N/A")
                        
                        sugars = nutr.get("sugars_100g")
                        st.metric("- Sugars", f"{sugars:.1f}g" if sugars is not None else "N/A")
                    
                    with ncol3:
                        protein = nutr.get("proteins_100g")
                        st.metric("Protein", f"{protein:.1f}g" if protein is not None else "N/A")
                        
                        fiber = nutr.get("fiber_100g")
                        st.metric("Fiber", f"{fiber:.1f}g" if fiber is not None else "N/A")
                    
                    with ncol4:
                        salt = nutr.get("salt_100g")
                        st.metric("Salt", f"{salt:.2f}g" if salt is not None else "N/A")
                        
                        sat_fat = nutr.get("saturated-fat_100g")
                        st.metric("Sat. Fat", f"{sat_fat:.1f}g" if sat_fat is not None else "N/A")
                
                # Ingredients section
                if prod.get("ingredients_text"):
                    st.markdown("#### 🥕 Ingredients")
                    st.info(prod.get("ingredients_text"))
                
                # Additional info in expanders
                col1, col2 = st.columns(2)
                
                with col1:
                    with st.expander("🔬 Detailed Nutriments"):
                        if nutr:
                            nutrient_data = []
                            for key, value in nutr.items():
                                if isinstance(value, (int, float)) and "_100g" in key and value >= 0:
                                    clean_key = key.replace("_100g", "").replace("-", " ").title()
                                    nutrient_data.append({"Nutrient": clean_key, "Per 100g": f"{value:.2f}"})
                            
                            if nutrient_data:
                                df_nutrients = pd.DataFrame(nutrient_data)
                                st.dataframe(df_nutrients, use_container_width=True, hide_index=True)
                            else:
                                st.info("No nutrition data available")
                        else:
                            st.info("No nutrition data available")
                
                with col2:
                    with st.expander("ℹ️ Product Information"):
                        info_data = {
                            "Categories": prod.get("categories"),
                            "Countries": prod.get("countries"),
                            "Labels": prod.get("labels"),
                            "Packaging": prod.get("packaging"),
                            "Quantity": prod.get("quantity"),
                        }
                        has_info = False
                        for key, value in info_data.items():
                            if value and str(value).strip():
                                st.markdown(f"**{key}:** {value}")
                                has_info = True
                        if not has_info:
                            st.info("No additional information available")
            else:
                st.error("❌ Product not found in database")
        except Exception as e:
            st.error(f"Error fetching product: {e}")

# Dashboard - only show if data exists
df = st.session_state.df

if df is not None and not df.empty:
    st.markdown("---")
    
    # Overview metrics - exclude unknowns
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🔢 Total Products", len(df))
    
    unique_brands = df["brands"].dropna()
    unique_brands = unique_brands[unique_brands.str.len() > 0].str.split(",").str[0].nunique()
    col2.metric("🏷️ Unique Brands", unique_brands)
    
    unique_countries = df["countries"].dropna()
    unique_countries = unique_countries[unique_countries.str.len() > 0].nunique()
    col3.metric("🌍 Countries", unique_countries)
    
    col4.metric("📊 With NutriScore", df["nutriscore"].notna().sum())

    # Tabs for organized content
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Nutrition", "🏆 Scores", "🏭 Brands", "🥕 Ingredients"])
    
    with tab1:
        st.subheader("Average Nutrients (per 100g)")
        nutrient_cols = ["energy_100g_kcal", "fat_100g", "saturated_fat_100g", 
                        "carbohydrates_100g", "sugars_100g", "fiber_100g", 
                        "proteins_100g", "salt_100g"]
        
        # Only calculate for columns with sufficient data
        avg_data = []
        for col in nutrient_cols:
            valid_count = df[col].notna().sum()
            if valid_count > 0:
                avg_val = df[col].mean(skipna=True)
                clean_name = col.replace("_100g", "").replace("_kcal", "").replace("_", " ").title()
                avg_data.append({"Nutrient": clean_name, "Average per 100g": avg_val, "Data Points": valid_count})
        
        if avg_data:
            avg_df = pd.DataFrame(avg_data)
            fig = px.bar(avg_df, x="Nutrient", y="Average per 100g", 
                        title="Average Nutritional Values", 
                        color="Average per 100g",
                        hover_data=["Data Points"],
                        color_continuous_scale="Viridis")
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
            
            st.caption(f"Based on products with available data. Hover for data point counts.")
        else:
            st.info("No nutrition data available")
    
    with tab2:
        st.subheader("NutriScore & EcoScore Distribution")
        
        col1, col2 = st.columns(2)
        
        with col1:
            nutri_data = df["nutriscore"].dropna().str.upper().value_counts()
            if not nutri_data.empty:
                fig = px.pie(values=nutri_data.values, names=nutri_data.index, 
                           title=f"NutriScore Distribution (n={nutri_data.sum()})",
                           color=nutri_data.index,
                           color_discrete_map={"A": "darkgreen", "B": "lightgreen", 
                                              "C": "yellow", "D": "orange", "E": "red"})
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No NutriScore data available")
        
        with col2:
            eco_data = df["ecoscore"].dropna().str.upper().value_counts()
            if not eco_data.empty:
                fig = px.pie(values=eco_data.values, names=eco_data.index,
                           title=f"EcoScore Distribution (n={eco_data.sum()})")
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
        available_nutri = df["nutriscore"].dropna().str.upper().unique().tolist()
        filter_nutri = st.multiselect("Filter by NutriScore", 
                                     options=sorted(available_nutri),
                                     default=[])
    with col2:
        available_brands = df["brands"].dropna()
        available_brands = available_brands[available_brands.str.len() > 0].str.split(",").str[0].str.strip().unique()
        filter_brand = st.selectbox("Filter by Brand", 
                                   options=["All"] + sorted(available_brands.tolist()))
    
    # Apply filters
    df_filtered = df.copy()
    if filter_nutri:
        df_filtered = df_filtered[df_filtered["nutriscore"].str.upper().isin(filter_nutri)]
    if filter_brand != "All":
        df_filtered = df_filtered[df_filtered["brands"].str.contains(filter_brand, case=False, na=False)]
    
    # Display filtered results - show only rows with meaningful data
    display_df = df_filtered[
        df_filtered["product_name"].notna()
    ][["product_name", "brands", "nutriscore", "ecoscore", "energy_100g_kcal", "barcode"]].head(50)
    
    # Replace None with user-friendly text only for display
    display_df = display_df.fillna("—")
    
    st.dataframe(
        display_df,
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
        sugar_df = df["sugars_100g"].dropna()
        if len(sugar_df) > 5:
            fig = px.histogram(sugar_df, x=sugar_df, 
                             nbins=30, title=f"Sugar Content Distribution (n={len(sugar_df)})",
                             labels={"x": "Sugars (g/100g)"})
            fig.update_traces(marker_color='#FF6B6B')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"Insufficient sugar data (only {len(sugar_df)} products)")
    
    with col2:
        protein_df = df["proteins_100g"].dropna()
        if len(protein_df) > 5:
            fig = px.histogram(protein_df, x=protein_df,
                             nbins=30, title=f"Protein Content Distribution (n={len(protein_df)})",
                             labels={"x": "Protein (g/100g)"})
            fig.update_traces(marker_color='#4ECDC4')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"Insufficient protein data (only {len(protein_df)} products)")
    
    with col3:
        fat_df = df["fat_100g"].dropna()
        if len(fat_df) > 5:
            fig = px.histogram(fat_df, x=fat_df,
                             nbins=30, title=f"Fat Content Distribution (n={len(fat_df)})",
                             labels={"x": "Fat (g/100g)"})
            fig.update_traces(marker_color='#FFE66D')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"Insufficient fat data (only {len(fat_df)} products)")
    
    # Row 2: Comparative Analysis
    st.subheader("Comparative Nutrient Analysis")
    col1, col2 = st.columns(2)
    
    with col1:
        scatter_df = df.dropna(subset=["energy_100g_kcal", "sugars_100g", "nutriscore"])
        if len(scatter_df) > 10:
            fig = px.scatter(scatter_df, x="sugars_100g", y="energy_100g_kcal",
                           color="nutriscore", 
                           title=f"Energy vs Sugar Content (n={len(scatter_df)})",
                           labels={"sugars_100g": "Sugars (g/100g)", 
                                  "energy_100g_kcal": "Energy (kcal/100g)"},
                           color_discrete_map={"a": "darkgreen", "b": "lightgreen", 
                                              "c": "yellow", "d": "orange", "e": "red"},
                           hover_data=["product_name", "brands"])
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"Insufficient data for energy vs sugar analysis (only {len(scatter_df)} products with complete data)")
    
    with col2:
        scatter_df2 = df.dropna(subset=["proteins_100g", "fat_100g", "nutriscore"])
        if len(scatter_df2) > 10:
            fig = px.scatter(scatter_df2, x="proteins_100g", y="fat_100g",
                           color="nutriscore",
                           title=f"Protein vs Fat Content (n={len(scatter_df2)})",
                           labels={"proteins_100g": "Protein (g/100g)", 
                                  "fat_100g": "Fat (g/100g)"},
                           color_discrete_map={"a": "darkgreen", "b": "lightgreen", 
                                              "c": "yellow", "d": "orange", "e": "red"},
                           hover_data=["product_name", "brands"])
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"Insufficient data for protein vs fat analysis (only {len(scatter_df2)} products with complete data)")
    
    # Row 3: Brand comparison
    st.subheader("Brand Comparison Dashboard")
    
    # Get top brands for detailed comparison
    brand_series = df["brands"].dropna()
    brand_series = brand_series[brand_series.str.len() > 0]
    
    if len(brand_series) > 0:
        top_brands_list = brand_series.str.split(",").str[0].str.strip().value_counts().head(8).index.tolist()
        brand_comp_df = df[df["brands"].notna()].copy()
        brand_comp_df["primary_brand"] = brand_comp_df["brands"].str.split(",").str[0].str.strip()
        brand_comp_df = brand_comp_df[brand_comp_df["primary_brand"].isin(top_brands_list)]
        
        if not brand_comp_df.empty:
            col1, col2 = st.columns(2)
            
            with col1:
                # Average nutrients by brand - only include brands with data
                nutrient_by_brand = brand_comp_df.groupby("primary_brand")[["energy_100g_kcal", "sugars_100g", "fat_100g", "proteins_100g"]].mean().reset_index()
                nutrient_by_brand = nutrient_by_brand.dropna(subset=["energy_100g_kcal", "sugars_100g", "fat_100g", "proteins_100g"], how='all')
                
                if not nutrient_by_brand.empty:
                    nutrient_melted = nutrient_by_brand.melt(id_vars="primary_brand", 
                                                             var_name="Nutrient", 
                                                             value_name="Average")
                    nutrient_melted = nutrient_melted.dropna(subset=["Average"])
                    
                    fig = px.bar(nutrient_melted, x="primary_brand", y="Average", 
                                color="Nutrient", barmode="group",
                                title="Average Nutrients by Top Brands",
                                labels={"primary_brand": "Brand", "Average": "Per 100g"})
                    fig.update_layout(xaxis_tickangle=-45)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Insufficient nutrient data for brand comparison")
            
            with col2:
                # NutriScore distribution by brand
                nutri_brand_df = brand_comp_df.dropna(subset=["nutriscore"])
                if not nutri_brand_df.empty:
                    nutri_by_brand = nutri_brand_df.groupby(["primary_brand", "nutriscore"]).size().reset_index(name="count")
                    fig = px.bar(nutri_by_brand, x="primary_brand", y="count", 
                                color="nutriscore", 
                                title="NutriScore Distribution by Brand",
                                labels={"primary_brand": "Brand", "count": "Number of Products"},
                                color_discrete_map={"a": "darkgreen", "b": "lightgreen", 
                                                   "c": "yellow", "d": "orange", "e": "red"})
                    fig.update_layout(xaxis_tickangle=-45)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Insufficient NutriScore data for brand comparison")
        else:
            st.info("Insufficient brand data for comparison")
    else:
        st.info("No brand data available")
    
    # Row 4: Advanced metrics
    st.subheader("Advanced Nutritional Metrics")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Calculate sugar-to-carb ratio
        ratio_df = df.dropna(subset=["sugars_100g", "carbohydrates_100g"])
        ratio_df = ratio_df[ratio_df["carbohydrates_100g"] > 0]
        if len(ratio_df) > 10:
            ratio_df["sugar_ratio"] = (ratio_df["sugars_100g"] / ratio_df["carbohydrates_100g"]) * 100
            # Filter out impossible ratios
            ratio_df = ratio_df[ratio_df["sugar_ratio"] <= 100]
            
            fig = px.histogram(ratio_df, x="sugar_ratio", nbins=30,
                             title=f"Sugar as % of Carbohydrates (n={len(ratio_df)})",
                             labels={"sugar_ratio": "Sugar Ratio (%)"})
            fig.update_traces(marker_color='#9B59B6')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"Insufficient data for sugar ratio (only {len(ratio_df)} products)")
    
    with col2:
        # Fiber content analysis
        fiber_df = df.dropna(subset=["fiber_100g", "nutriscore"])
        if len(fiber_df) > 10:
            fig = px.violin(fiber_df, x="nutriscore", y="fiber_100g",
                          title=f"Fiber Content by NutriScore (n={len(fiber_df)})",
                          labels={"nutriscore": "NutriScore", "fiber_100g": "Fiber (g/100g)"},
                          color="nutriscore",
                          color_discrete_map={"a": "darkgreen", "b": "lightgreen", 
                                             "c": "yellow", "d": "orange", "e": "red"})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"Insufficient fiber data (only {len(fiber_df)} products)")
    
    with col3:
        # Saturated fat percentage
        sat_df = df.dropna(subset=["saturated_fat_100g", "fat_100g"])
        sat_df = sat_df[sat_df["fat_100g"] > 0]
        if len(sat_df) > 10:
            sat_df["sat_fat_ratio"] = (sat_df["saturated_fat_100g"] / sat_df["fat_100g"]) * 100
            # Filter out impossible ratios
            sat_df = sat_df[sat_df["sat_fat_ratio"] <= 100]
            
            fig = px.histogram(sat_df, x="sat_fat_ratio", nbins=30,
                             title=f"Saturated Fat as % of Total Fat (n={len(sat_df)})",
                             labels={"sat_fat_ratio": "Saturated Fat Ratio (%)"})
            fig.update_traces(marker_color='#E67E22')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"Insufficient saturated fat data (only {len(sat_df)} products)")
    
    # Row 5: Correlation heatmap
    st.subheader("Nutrient Correlation Matrix")
    corr_cols = ["energy_100g_kcal", "fat_100g", "saturated_fat_100g", 
                 "carbohydrates_100g", "sugars_100g", "fiber_100g", 
                 "proteins_100g", "salt_100g"]
    corr_df = df[corr_cols].dropna()
    
    if len(corr_df) > 20:
        correlation_matrix = corr_df.corr()
        fig = px.imshow(correlation_matrix, 
                       title=f"Correlation Between Nutrients (n={len(corr_df)} products)",
                       labels=dict(color="Correlation"),
                       x=correlation_matrix.columns,
                       y=correlation_matrix.columns,
                       color_continuous_scale="RdBu_r",
                       aspect="auto",
                       text_auto='.2f')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(f"Insufficient data for correlation analysis (only {len(corr_df)} products with complete nutrient data)")
    
    # Row 6: Summary statistics table
    st.subheader("📊 Summary Statistics")
    summary_stats = df[corr_cols].describe().T
    summary_stats["count"] = summary_stats["count"].astype(int)
    summary_stats = summary_stats[["count", "mean", "std", "min", "50%", "max"]]
    summary_stats.columns = ["Valid Products", "Mean", "Std Dev", "Min", "Median", "Max"]
    summary_stats.index = [col.replace("_100g", "").replace("_kcal", "").replace("_", " ").title() for col in corr_cols]
    summary_stats.index.name = "Nutrient"
    
    st.dataframe(
        summary_stats.style.background_gradient(cmap="YlOrRd", subset=["Mean", "Std Dev", "Min", "Median", "Max"], axis=1).format({
            "Valid Products": "{:.0f}",
            "Mean": "{:.2f}",
            "Std Dev": "{:.2f}",
            "Min": "{:.2f}",
            "Median": "{:.2f}",
            "Max": "{:.2f}"
        }), 
        use_container_width=True
    )
    
    # Data quality report
    st.markdown("---")
    st.subheader("📋 Data Quality Report")
    
    quality_data = []
    for col in corr_cols:
        total = len(df)
        valid = df[col].notna().sum()
        missing = total - valid
        completeness = (valid / total * 100) if total > 0 else 0
        
        clean_name = col.replace("_100g", "").replace("_kcal", "").replace("_", " ").title()
        quality_data.append({
            "Field": clean_name,
            "Valid": valid,
            "Missing": missing,
            "Completeness (%)": completeness
        })
    
    # Add non-numeric fields
    for field, display_name in [("product_name", "Product Name"), ("brands", "Brands"), 
                                 ("nutriscore", "NutriScore"), ("ecoscore", "EcoScore")]:
        total = len(df)
        valid = df[field].notna().sum()
        missing = total - valid
        completeness = (valid / total * 100) if total > 0 else 0
        
        quality_data.append({
            "Field": display_name,
            "Valid": valid,
            "Missing": missing,
            "Completeness (%)": completeness
        })
    
    quality_df = pd.DataFrame(quality_data)
    quality_df = quality_df.sort_values("Completeness (%)", ascending=False)
    
    fig = px.bar(quality_df, x="Field", y="Completeness (%)",
                title="Data Completeness by Field",
                color="Completeness (%)",
                color_continuous_scale="RdYlGn",
                range_color=[0, 100])
    fig.update_layout(xaxis_tickangle=-45)
    fig.add_hline(y=50, line_dash="dash", line_color="red", 
                  annotation_text="50% threshold", annotation_position="right")
    st.plotly_chart(fig, use_container_width=True)
    
    with st.expander("View detailed completeness table"):
        st.dataframe(
            quality_df.style.background_gradient(cmap="RdYlGn", subset=["Completeness (%)"], vmin=0, vmax=100).format({
                "Valid": "{:.0f}",
                "Missing": "{:.0f}",
                "Completeness (%)": "{:.1f}%"
            }),
            use_container_width=True,
            hide_index=True
        )

else:
    st.info("👈 Use the sidebar to search for products or lookup a specific barcode")
    st.markdown("""
    ### How to use NutriLens:
    1. **Search Products**: Enter a keyword, country, or category in the sidebar
    2. **Lookup Barcode**: Enter a specific product barcode for detailed info
    3. **Explore Data**: View nutrition averages, scores, brands, and ingredients
    
    ### Data Quality Features:
    - ✅ Automatic filtering of invalid/unknown values
    - ✅ Outlier detection for unrealistic nutrient values
    - ✅ Data completeness indicators on all charts
    - ✅ Transparent reporting of missing data
    
    Data source: [Open Food Facts](https://world.openfoodfacts.org/)
    """)

st.markdown("---")
st.caption("💡 Data from Open Food Facts | Coverage varies by product | Charts show only valid data points")
