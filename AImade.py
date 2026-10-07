import concurrent.futures
import re
import urllib.parse
import cloudscraper
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="Ottawa TCG Card Finder",
    page_icon="🃏",
    layout="wide"
)

# ==========================================
# 1. HELPER: PRICE CLEANER
# ==========================================
def parse_price(val) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    if not val:
        return 99999.0
    match = re.search(r"(\d+(?:\.\d{1,2})?)", str(val).replace(",", ""))
    return float(match.group(1)) if match else 99999.0

# ==========================================
# 2. STORE SCRAPERS (WITH IMAGES)
# ==========================================
def search_crystalcommerce(store_name: str, base_domain: str, query: str):
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    safe_query = urllib.parse.quote_plus(query)
    url = f"https://{base_domain}/advanced_search?utf8=%E2%9C%93&search%5Bfuzzy_search%5D={safe_query}&search%5Bin_stock%5D=1&commit=Search"
    
    for _ in range(3):
        try:
            resp = scraper.get(url, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                results = []
                for item in soup.select('li.product'):
                    name_tag = item.select_one('.name')
                    variant_row = item.select_one('.variant-row.in-stock')
                    if not (name_tag and variant_row): continue
                    
                    price_tag = variant_row.select_one('.regular.price')
                    qty_tag = variant_row.select_one('.variant-qty')
                    desc_tag = variant_row.select_one('.variant-description')
                    link_tag = item.select_one('a')
                    
                    img_tag = item.select_one('.image img')
                    img_url = img_tag['src'] if img_tag else None

                    results.append({
                        "Image": img_url,
                        "Store": store_name,
                        "Product": name_tag.get_text(strip=True),
                        "Price": parse_price(price_tag.get_text(strip=True) if price_tag else 0),
                        "Stock": qty_tag.get_text(strip=True) if qty_tag else "In Stock",
                        "Condition": desc_tag.get_text(strip=True) if desc_tag else "Unknown",
                        "URL": f"https://{base_domain}{link_tag['href']}" if link_tag else f"https://{base_domain}"
                    })
                return results
        except Exception:
            continue
    return []

def search_shopify(store_name: str, domain: str, query: str):
    url = f"https://{domain}/search/suggest.json"
    params = {"q": query, "resources[type]": "product"}
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=6)
        if resp.status_code != 200: return []
        products = resp.json().get('resources', {}).get('results', {}).get('products', [])
        
        results = []
        for item in products:
            if item.get('available'):
                img_url = item.get('image', None)
                if img_url and img_url.startswith('//'):
                    img_url = f"https:{img_url}"

                results.append({
                    "Image": img_url,
                    "Store": store_name,
                    "Product": item['title'],
                    "Price": parse_price(item.get('price', 0)),
                    "Stock": "In Stock",
                    "Condition": "Standard",
                    "URL": f"https://{domain}{item['url']}"
                })
        return results
    except Exception:
        return []

def search_binderpos(store_name: str, base_url: str, store_id: str, query: str):
    api_url = "https://store.storepass.co/saas/search"
    params = {"store_id": store_id, "name": query, "limit": "30", "in_stock": "undefined", "fields": "url,price,name,variantInfo,stock,image_url,image"}
    headers = {"User-Agent": "Mozilla/5.0", "Origin": base_url, "Referer": f"{base_url}/"}
    
    try:
        resp = requests.get(api_url, params=params, headers=headers, timeout=6)
        if resp.status_code != 200: return []
        data = resp.json()
        products = data.get('results', data.get('products', data.get('data', [])))
        if not products and isinstance(data, list): products = data
            
        results = []
        for item in products:
            raw_url = item.get('url', '')
            final_url = raw_url if raw_url.startswith('http') else f"{base_url.rstrip('/')}/products/{raw_url.lstrip('/')}"
            base_name = item.get('name', 'Unknown Card')
            variant_info = item.get('variant_info', item.get('variantInfo', []))
            
            img_url = item.get('image_url', item.get('image', None))
            if img_url and img_url.startswith('//'):
                img_url = f"https:{img_url}"

            if isinstance(variant_info, list):
                for variant in variant_info:
                    stock = variant.get('inventory_quantity', 0)
                    if stock > 0:
                        cond = variant.get('title') or variant.get('option1') or "Unknown"
                        results.append({
                            "Image": img_url,
                            "Store": store_name,
                            "Product": base_name,
                            "Price": parse_price(variant.get('price', item.get('price'))),
                            "Stock": f"{stock} available",
                            "Condition": cond,
                            "URL": final_url
                        })
        return results
    except Exception:
        return []

# ==========================================
# 3. STORE REGISTRY (WITH ADDRESSES)
# ==========================================
STORE_REGISTRY = {
    "Carta Magica": {
        "type": "crystalcommerce", "domain": "www.cartamagicaottawa.com", 
        "lat": 45.4326, "lon": -75.6375, "address": "1179 St. Laurent Blvd, Ottawa"
    },
    "Trinity Hobby": {
        "type": "shopify", "domain": "trinityhobby.com", 
        "lat": 45.3854, "lon": -75.7360, "address": "1320 Carling Avenue, Ottawa"
    },
    "Nabema Collectibles": {
        "type": "shopify", "domain": "www.nabemacollectibles.com", 
        "lat": 45.4651, "lon": -75.5460, "address": "1615 Orléans Blvd, Orléans"
    },
    "Red Dragon": {
        "type": "shopify", "domain": "red-dragon.ca", 
        "lat": 45.4800, "lon": -75.4740, "address": "6008 Voyageur Dr, Orléans"
    },
    "Multizone": {
        "type": "shopify", "domain": "multizone.ca", 
        "lat": 45.4849, "lon": -75.6994, "address": "140 Blvd Greber, Gatineau"
    },
    "GameBreakers": {
        "type": "shopify", "domain": "gamebreakers.ca", 
        "lat": 45.3619, "lon": -75.7482, "address": "780 Baseline Rd, Ottawa"
    },
    "Hobbiesville": {
        "type": "shopify", "domain": "hobbiesville.com", 
        "lat": 45.4116, "lon": -75.7027, "address": "607 Somerset St W, Ottawa"
    },
    "GT Games": {
        "type": "binderpos", "base_url": "https://gtgames.ca", "store_id": "eSWnGFPNHn", 
        "lat": 45.4678, "lon": -75.4952, "address": "Online / Ottawa Area"
    }
}

# ==========================================
# 4. CONCURRENT RUNNER
# ==========================================
def scrape_selected_stores(selected_store_names: list[str], search_term: str):
    all_results = []
    with st.status(f"Searching {len(selected_store_names)} store(s) for '{search_term}'...", expanded=True) as status:
        tasks = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            for name in selected_store_names:
                cfg = STORE_REGISTRY.get(name)
                if not cfg: continue
                
                if cfg["type"] == "crystalcommerce":
                    future = executor.submit(search_crystalcommerce, name, cfg["domain"], search_term)
                elif cfg["type"] == "shopify":
                    future = executor.submit(search_shopify, name, cfg["domain"], search_term)
                elif cfg["type"] == "binderpos":
                    future = executor.submit(search_binderpos, name, cfg["base_url"], cfg["store_id"], search_term)
                else: continue
                tasks[future] = name

            for future in concurrent.futures.as_completed(tasks):
                store_name = tasks[future]
                try:
                    res = future.result()
                    all_results.extend(res)
                    st.write(f"✓ {store_name} ({len(res)} items found)")
                except Exception:
                    st.write(f"⚠ {store_name} timed out or failed")
                    
        status.update(label="Search complete!", state="complete", expanded=False)
    return all_results

# ==========================================
# 5. HTML MAP GENERATOR
# ==========================================
def generate_leaflet_map(store_data_list):
    """Generates an interactive HTML map with hover tooltips and click links."""
    markers_js = ""
    for store in store_data_list:
        # Build HTML list of cards available at this store
        cards_html = "".join([f"<li>{c['name']} - <b>${c['price']:.2f}</b></li>" for c in store['cards']])
        
        # Design the tooltip popup
        tooltip_html = f"""
        <div style='min-width: 220px;'>
            <h4 style='margin: 0 0 4px 0; color: #1f77b4;'>{store['name']}</h4>
            <p style='margin: 0 0 10px 0; font-size: 11px; color: #555;'>{store['address']}</p>
            <strong style='font-size: 12px;'>Available Inventory:</strong>
            <ul style='padding-left: 15px; margin: 4px 0 0 0; font-size: 12px; max-height: 120px; overflow-y: auto;'>
                {cards_html}
            </ul>
            <p style='margin: 10px 0 0 0; font-size: 11px; font-weight: bold; color: #2ca02c; text-align: center;'>
                👉 Click marker to open in Google Maps
            </p>
        </div>
        """
        
        # Escape newlines so JS doesn't break
        tooltip_html = tooltip_html.replace("`", "\\`").replace("\n", "")
        maps_url = store['maps_url'].replace("'", "\\'")
        
        # Add JavaScript instructions for this marker
        markers_js += f"""
        var marker = L.marker([{store['lat']}, {store['lon']}]).addTo(map);
        marker.bindTooltip(`{tooltip_html}`, {{direction: 'top'}});
        marker.on('click', function() {{
            window.open('{maps_url}', '_blank');
        }});
        """

    # Assemble the full Leaflet Document
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
            body {{ margin: 0; padding: 0; font-family: sans-serif; }}
            #map {{ height: 100vh; width: 100vw; border-radius: 8px; }}
        </style>
    </head>
    <body>
        <div id="map"></div>
        <script>
            // Center the map on Ottawa
            var map = L.map('map').setView([45.4215, -75.6972], 11);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                maxZoom: 19,
                attribution: '© OpenStreetMap'
            }}).addTo(map);
            
            // Add our dynamically generated markers
            {markers_js}
        </script>
    </body>
    </html>
    """

# ==========================================
# 6. STREAMLIT UI
# ==========================================
with st.sidebar:
    st.header("Store Filters")
    all_stores = list(STORE_REGISTRY.keys())
    if "selected_stores" not in st.session_state: st.session_state.selected_stores = all_stores

    col_btn1, col_btn2 = st.columns(2)
    if col_btn1.button("Select All", use_container_width=True): st.session_state.selected_stores = all_stores
    if col_btn2.button("Clear All", use_container_width=True): st.session_state.selected_stores = []

    chosen_stores = st.multiselect("Stores to query:", options=all_stores, default=st.session_state.selected_stores)

st.title("🃏 Ottawa TCG Card Aggregator")

with st.form("search_form"):
    col1, col2 = st.columns([4, 1])
    with col1: query = st.text_input("Enter card name:", placeholder="e.g. Sheoldred, the Apocalypse")
    with col2: 
        st.write("") 
        st.write("")
        submit = st.form_submit_button("Search", type="primary", use_container_width=True)

if submit:
    if not chosen_stores: st.error("Please select at least one store in the sidebar.")
    elif not query.strip(): st.warning("Please enter a card name to search.")
    else:
        raw_data = scrape_selected_stores(chosen_stores, query.strip())
        filtered = [r for r in raw_data if query.lower() in r["Product"].lower()]
        
        if not filtered:
            st.warning(f"No in-stock listings found matching '{query}' across the selected store(s).")
        else:
            df = pd.DataFrame(filtered).sort_values(by="Price", ascending=True)
            
            # --- METRICS & INTERACTIVE MAP SECTION ---
            col_metrics, col_map = st.columns([1, 2])
            
            with col_metrics:
                st.subheader("Results Summary")
                st.metric("Total Listings", len(df))
                st.metric("Lowest Price", f"${df['Price'].min():.2f} CAD")
                st.metric("Stores with Stock", df["Store"].nunique())
            
            with col_map:
                st.subheader("In-Stock Locations")
                # Group our results by store so we can build the list of cards for the tooltip
                store_groups = df.groupby("Store")
                map_data = []
                
                for s, group in store_groups:
                    if s in STORE_REGISTRY:
                        cfg = STORE_REGISTRY[s]
                        
                        # Bundle the cards available at this specific store
                        cards_list = [{"name": row["Product"], "price": row["Price"]} for _, row in group.iterrows()]
                        
                        # Generate a clean Google Maps search URL
                        search_target = urllib.parse.quote(f"{s} {cfg['address']}")
                        maps_url = f"https://www.google.com/maps/search/?api=1&query={search_target}"
                        
                        map_data.append({
                            "name": s,
                            "address": cfg["address"],
                            "lat": cfg["lat"],
                            "lon": cfg["lon"],
                            "maps_url": maps_url,
                            "cards": cards_list
                        })
                
                # Render the map Component
                if map_data:
                    leaflet_html = generate_leaflet_map(map_data)
                    components.html(leaflet_html, height=450)
            
            st.write("---")
            
            # --- DATA TABLE WITH IMAGES ---
            st.subheader("Detailed Inventory")
            st.dataframe(
                df,
                column_config={
                    "Image": st.column_config.ImageColumn(
                        "Preview", help="Card Image Preview"
                    ),
                    "Price": st.column_config.NumberColumn(
                        "Price (CAD)", format="$%.2f"
                    ),
                    "URL": st.column_config.LinkColumn(
                        "Store Link", display_text="View on Store ↗"
                    ),
                },
                use_container_width=True,
                hide_index=True
            )