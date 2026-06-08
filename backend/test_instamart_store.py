import sys
import json
import re
from curl_cffi import requests

def fetch_html_with_store(store_id, lat, lng):
    url = f"https://www.swiggy.com/instamart/item/54ZJRDYZYL"
    cookies = {
        "lat": str(lat),
        "lng": str(lng),
        "storeId": str(store_id)
    }
    
    session = requests.Session(impersonate="chrome124")
    res = session.get(url, cookies=cookies, timeout=10)
    text = res.text
    
    title = "Unknown"
    price = None
    mrp = None
    status = "error"
    is_sold_out = False
    
    # 1. Schema approach
    schema_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.DOTALL)
    if schema_match:
        try:
            data = json.loads(schema_match.group(1))
            title = data.get("name", "Unknown")
            offers = data.get("offers", {})
            price = float(offers.get("price")) if offers.get("price") else None
            
            avail = offers.get("availability", "")
            if "OutOfStock" in avail:
                is_sold_out = True
                status = "out_of_stock"
            elif "InStock" in avail:
                status = "available"
        except Exception as e:
            print("schema error", e)

    # 2. Extract MRP
    mrp_match = re.search(r'data-testid="item-mrp-price"[^>]*>(\d+(\.\d+)?)<', text)
    if mrp_match:
        mrp = float(mrp_match.group(1))
    
    if not mrp and price:
        mrp = price
        
    print(f"Store {store_id}: title={title}, price={price}, mrp={mrp}, status={status}")

if __name__ == "__main__":
    fetch_html_with_store("1389691", 18.570437, 73.908812) # Pune
    fetch_html_with_store("1231052", 12.912604, 77.652616) # Bangalore
