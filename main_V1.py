import requests
import cloudscraper
from bs4 import BeautifulSoup
import json
import urllib.parse
import streamlit as st

import time # <-- Add this to your imports at the top!

# ==========================================
# 1. CRYSTAL COMMERCE SCRAPER (HTML Parsing)
# ==========================================
def search_crystalcommerce(store_name, base_domain, query):
    # Create a scraper to bypass Cloudflare
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    
    # URL encode the search term
    safe_query = urllib.parse.quote_plus(query)
    
    url = f"https://{base_domain}/advanced_search?utf8=%E2%9C%93&search%5Bfuzzy_search%5D={safe_query}&search%5Btags_name_eq%5D=&search%5Bsell_price_gte%5D=&search%5Bsell_price_lte%5D=&search%5Bbuy_price_gte%5D=&search%5Bbuy_price_lte%5D=&search%5Bin_stock%5D=0&search%5Bin_stock%5D=1&buylist_mode=0&search%5Bcategory_ids_with_descendants%5D%5B%5D=&search%5Bcategory_ids_with_descendants%5D%5B%5D=&search%5Bsort%5D=name&search%5Bdirection%5D=ascend&commit=Search&search%5Bcatalog_group_id_eq%5D="
    
    max_retries = 5
    response = None
    
    # The Brute-Force Retry Loop
    for attempt in range(max_retries):
        try:
            response = scraper.get(url, timeout=10)
            if response.status_code == 200:
                break # It worked! Break out of the retry loop.
        except Exception as e:
            st.write(f"  [!] {store_name} connection dropped (Attempt {attempt + 1}/{max_retries}). Retrying in 2s...")
            time.sleep(2)
            
    # If we tried 3 times and still don't have a good response, give up gracefully
    if not response or response.status_code != 200:
        st.write(f"  [X] Failed to connect to {store_name} after {max_retries} attempts.")
        return []

    # If it succeeded, parse the HTML
    soup = BeautifulSoup(response.text, 'html.parser')
    results = []
    items = soup.select('li.product')

    for item in items:
        name_tag = item.select_one('.name')
        category_tag = item.select_one('.category')
        variant_row = item.select_one('.variant-row.in-stock')
        
        if name_tag and variant_row:
            name = name_tag.text.strip()
            category = category_tag.text.strip() if category_tag else "Unknown"
            
            condition_tag = variant_row.select_one('.variant-description')
            qty_tag = variant_row.select_one('.variant-qty')
            price_tag = variant_row.select_one('.regular.price')
            
            link_tag = item.select_one('a')
            url_link = f"https://{base_domain}{link_tag['href']}" if link_tag else f"https://{base_domain}"
            
            results.append({
                "store": store_name,
                "name": name,
                "price": price_tag.text.strip() if price_tag else "Unknown",
                "url": url_link,
                "stock_status": qty_tag.text.strip() if qty_tag else "Unknown",
                "condition": condition_tag.text.strip() if condition_tag else "Unknown",
                "category": category
            })
    return results

# ==========================================
# 2. SHOPIFY SCRAPER (Native API)
# ==========================================
def search_shopify(store_name, domain, query):
    url = f"https://{domain}/search/suggest.json"
    params = {"q": query, "resources[type]": "product"}
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = requests.get(url, params=params, headers=headers)
        if response.status_code != 200: return []
    except Exception:
        return []

    results = []
    data = response.json()
    products = data.get('resources', {}).get('results', {}).get('products', [])
    
    for item in products:
        if item.get('available'):
            results.append({
                "store": store_name,
                "name": item['title'],
                "price": f"CAD$ {item['price']}",
                "url": f"https://{domain}{item['url']}",
                "stock_status": "In Stock", 
                "condition": "Unknown",
                "category": "Unknown"
            })
    return results

# ==========================================
# 3. BINDERPOS SCRAPER (Storepass API)
# ==========================================
def search_binderpos(store_name, base_url, store_id, query):
    api_url = "https://store.storepass.co/saas/search"
    params = {
        "store_id": store_id, "name": query, "limit": "30", "in_stock": "undefined",  
        "fields": "url,price,name,variantInfo,stock",
    }
    headers = {"User-Agent": "Mozilla/5.0", "Origin": base_url, "Referer": f"{base_url}/"}
    
    try:
        response = requests.get(api_url, params=params, headers=headers)
        if response.status_code != 200: return []
    except Exception:
        return []

    results = []
    data = response.json()
    products = data.get('results', data.get('products', data.get('data', [])))
    if not products and isinstance(data, list): products = data
        
    for item in products:
        raw_url = item.get('url', '')
        final_url = raw_url if raw_url.startswith('http') else f"{base_url.rstrip('/')}/products/{raw_url.lstrip('/')}"
        base_name = item.get('name', 'Unknown Card')
        variant_info = item.get('variant_info', item.get('variantInfo', []))
        
        if isinstance(variant_info, list):
            for variant in variant_info:
                stock = variant.get('inventory_quantity', 0)
                if stock > 0:
                    condition = variant.get('title', 'Unknown')
                    if condition in ['Unknown', 'Default Title']: condition = variant.get('option1', 'Unknown')
                    price = variant.get('price', item.get('price', 'Unknown'))
                    results.append({"store": store_name, "name": base_name, "price": f"CAD$ {price}", "url": final_url, "stock_status": f"{stock} In Stock", "condition": condition, "category": "Unknown"})
        elif isinstance(variant_info, dict):
            stock = item.get('stock', 0)
            if stock > 0:
                results.append({"store": store_name, "name": base_name, "price": f"CAD$ {item.get('price')}", "url": final_url, "stock_status": f"{stock} In Stock", "condition": variant_info.get('condition', 'Unknown'), "category": "Unknown"})
                
    return results

# ==========================================
# 4. HELPER: PRICE SORTER
# ==========================================
def extract_price(item):
    """Converts 'CAD$ 1.50' into a float 1.50 so Python can sort it properly."""
    raw_price = item.get('price', '99999')
    try:
        # Strip out the letters and symbols
        clean_price = raw_price.replace("CAD$", "").replace(",", "").strip()
        return float(clean_price)
    except ValueError:
        return 99999.0 # If the price is broken/unknown, push it to the bottom of the list

# ==========================================
# MAIN EXECUTION BLOCK
# ==========================================
if __name__ == "__main__":
    st.write("hello")
    # --- EDIT YOUR SEARCH TERM HERE ---
    search_term = st.text_input("card search")
    # ----------------------------------
    

    if (st.button("search")):
        st.write(f"🔎 Executing Local Ottawa Search for: '{search_term}'\n")
        all_results = []
        
        # 1. CRYSTAL COMMERCE
        st.write("Scraping Carta Magica...")
        #all_results.extend(search_crystalcommerce("Carta Magica", "www.cartamagicaottawa.com", search_term))
        
        # 2. SHOPIFY STORES
        shopify_stores = [
            {"name": "Trinity Hobby", "domain": "trinityhobby.com"},
            {"name": "Nabema Collectibles", "domain": "www.nabemacollectibles.com"},
            {"name": "Red Dragon", "domain": "red-dragon.ca"},
            {"name": "Multizone", "domain": "multizone.ca"},
            {"name": "GameBreakers", "domain": "gamebreakers.ca"},
            {"name": "Hobbiesville", "domain": "hobbiesville.com"}
        ]
        for store in shopify_stores:
            st.write(f"Scraping {store['name']}...")
            all_results.extend(search_shopify(store["name"], store["domain"], search_term))
            
        # 3. BINDERPOS STORES
        st.write("Scraping GT Games...")
        all_results.extend(search_binderpos("GT Games", "https://gtgames.ca", "eSWnGFPNHn", search_term))
        
        # --- SORT THE FINAL LIST BY PRICE (LOWEST TO HIGHEST) ---
        all_results.sort(key=extract_price)
        
        # --- st.write THE RESULTS ---
        st.write(f"\n✅ Found {len(all_results)} in-stock items across all local stores!")
        st.write("\n--- FINAL SORTED RESULTS ---")
        filtered_results = [res for res in all_results if "name" in res and search_term.lower() in res["name"].lower()]
        st.write(json.dumps(filtered_results, indent=4))