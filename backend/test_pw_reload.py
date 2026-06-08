from playwright.sync_api import sync_playwright
import time
import json
import re

def test_pw_reload():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # 1. Load without cookies to solve WAF
        print("Solving WAF without cookies...")
        page.goto("https://www.swiggy.com/instamart/item/54ZJRDYZYL", wait_until="networkidle")
        page.wait_for_timeout(3000)
        
        # 2. Add cookies
        print("Adding cookies...")
        context.add_cookies([
            {"name": "lat", "value": "12.912604", "domain": ".swiggy.com", "path": "/"},
            {"name": "lng", "value": "77.652616", "domain": ".swiggy.com", "path": "/"},
            {"name": "storeId", "value": "1231052", "domain": ".swiggy.com", "path": "/"}
        ])
        
        # 3. Reload
        print("Reloading...")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(3000)
        
        content = page.content()
        schema_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', content, re.DOTALL)
        if schema_match:
            data = json.loads(schema_match.group(1))
            price = data.get("offers", {}).get("price")
            print(f"Success: price is {price}")
        else:
            if "AWS WAF" in content or "challenge.js" in content:
                print("Failed: WAF Blocked on reload")
            else:
                print("Failed: no schema")

        browser.close()

if __name__ == "__main__":
    test_pw_reload()
