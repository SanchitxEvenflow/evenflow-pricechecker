from playwright.sync_api import sync_playwright
from proxy.manager import ProxyManager

def test_playwright_proxy():
    pm = ProxyManager("proxies.txt")
    proxy = pm.get_proxy()
    print("Using proxy:", proxy)
    
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        context = browser.new_context(
            proxy={"server": proxy} if proxy else None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0"
        )
        page = context.new_page()
        print("Navigating...")
        
        # We need to set cookies for store
        context.add_cookies([
            {"name": "lat", "value": "18.570437", "domain": ".swiggy.com", "path": "/"},
            {"name": "lng", "value": "73.908812", "domain": ".swiggy.com", "path": "/"},
            {"name": "storeId", "value": "1389691", "domain": ".swiggy.com", "path": "/"}
        ])
        
        response = page.goto("https://www.swiggy.com/instamart/item/54ZJRDYZYL", wait_until="networkidle")
        print("Status:", response.status)
        
        content = page.content()
        if "AWS WAF" in content or "challenge.js" in content:
            print("WAF Challenge detected! Waiting 5s to see if it solves it...")
            page.wait_for_timeout(5000)
            content = page.content()
            if "AWS WAF" in content or "challenge.js" in content:
                print("WAF STILL NOT SOLVED")
            else:
                print("WAF SOLVED!")
        else:
            print("No WAF challenge!")
            
        import re
        import json
        schema_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', content, re.DOTALL)
        if schema_match:
            print("Schema found!")
        else:
            print("No schema")
            
        browser.close()

if __name__ == "__main__":
    test_playwright_proxy()
