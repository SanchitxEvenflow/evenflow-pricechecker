from playwright.sync_api import sync_playwright

def get_waf_token():
    print("Launching Playwright to solve WAF...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        response = page.goto("https://www.swiggy.com/instamart/item/54ZJRDYZYL", wait_until="networkidle")
        
        # wait a bit for JS challenge to run
        page.wait_for_timeout(3000)
        
        cookies = context.cookies()
        waf_token = None
        for c in cookies:
            if "aws-waf-token" in c["name"]:
                waf_token = c["value"]
                print("Found WAF token:", waf_token)
                
        browser.close()
        return waf_token

if __name__ == "__main__":
    token = get_waf_token()
    if token:
        print("Got token!")
    else:
        print("Failed to get token")
