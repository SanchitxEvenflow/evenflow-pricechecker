from playwright.sync_api import sync_playwright
import time
import json
import re

def test_pw_caching():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        cities = [
            {"name": "Bangalore", "lat": "12.912604", "lng": "77.652616", "storeId": "1231052"},
            {"name": "Pune", "lat": "18.570437", "lng": "73.908812", "storeId": "1389691"}
        ]
        
        for c in cities:
            print(f"Testing {c['name']}...")
            context.add_cookies([
                {"name": "lat", "value": c["lat"], "domain": ".swiggy.com", "path": "/"},
                {"name": "lng", "value": c["lng"], "domain": ".swiggy.com", "path": "/"},
                {"name": "storeId", "value": c["storeId"], "domain": ".swiggy.com", "path": "/"}
            ])
            
            # bypass cache with timestamp
            page.goto(f"https://www.swiggy.com/instamart/item/54ZJRDYZYL?_t={time.time()}", wait_until="networkidle")
            page.wait_for_timeout(3000)
            
            content = page.content()
            schema_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', content, re.DOTALL)
            if schema_match:
                data = json.loads(schema_match.group(1))
                price = data.get("offers", {}).get("price")
                print(f"Success: {c['name']} price is {price}")

        browser.close()

if __name__ == "__main__":
    test_pw_caching()
