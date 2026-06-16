"""
get_store_ids.py

A standalone script to fetch store IDs for Zepto and Instamart using location coordinates.
Note: Blinkit does not require a store_id in this architecture (it uses lat/lon cookies).

Usage:
    python get_store_ids.py --lat 12.912604 --lng 77.652616 --pincode 560102
"""

import asyncio
import argparse
import re
from playwright.async_api import async_playwright

async def get_zepto_store_id(lat: float, lng: float, pincode: str) -> str:
    """
    Simulates a browser visit to Zepto with mocked geolocation to intercept
    the internal API calls and extract the assigned store_id.
    """
    store_id = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            geolocation={"latitude": lat, "longitude": lng},
            permissions=['geolocation']
        )
        page = await context.new_page()
        
        async def handle_response(response):
            nonlocal store_id
            if store_id:
                return  # already found
            
            url = response.url
            if "api/v2/get_page" in url or "v3/location" in url or "layout" in url:
                try:
                    req = response.request
                    headers = req.headers
                    if "tenant" in headers:
                        if "storeid" in headers:
                            store_id = headers["storeid"]
                        elif "store_id" in headers:
                            store_id = headers["store_id"]
                except Exception:
                    pass

        page.on("response", handle_response)
        
        try:
            await page.goto("https://www.zepto.com/", wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(5000)
        except Exception as e:
            pass

        await browser.close()
        
    return store_id

async def get_instamart_store_id(lat: float, lng: float, pincode: str) -> str:
    """
    Simulates a browser visit to Swiggy Instamart with mocked geolocation.
    Note: Swiggy often requires manual address selection if geolocation doesn't automatically map to a serviceable zone.
    This is a best-effort automated extraction.
    """
    store_id = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            geolocation={"latitude": lat, "longitude": lng},
            permissions=['geolocation']
        )
        
        # Swiggy uses cookies for lat/lng heavily
        await context.add_cookies([
            {"name": "lat", "value": str(lat), "domain": ".swiggy.com", "path": "/"},
            {"name": "lng", "value": str(lng), "domain": ".swiggy.com", "path": "/"}
        ])
        
        page = await context.new_page()
        
        async def handle_response(response):
            nonlocal store_id
            if store_id: return
            
            try:
                # 1. Check request headers
                headers = response.request.headers
                if "storeid" in headers:
                    store_id = headers["storeid"]
                elif "store-id" in headers:
                    store_id = headers["store-id"]
                
                # 2. Check response body if it's JSON
                if not store_id:
                    content_type = response.headers.get("content-type", "")
                    if "application/json" in content_type:
                        text = await response.text()
                        m = re.search(r'"storeId"\s*:\s*"?(\d+)"?', text)
                        if m:
                            store_id = str(m.group(1))
            except Exception:
                pass

        page.on("response", handle_response)
        
        try:
            await page.goto("https://www.swiggy.com/instamart", wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(5000)
        except Exception as e:
            pass

        await browser.close()
        
    return store_id

def get_blinkit_store_id(lat: float, lng: float, pincode: str) -> str:
    """
    Blinkit relies entirely on lat/lon cookies (`gr_1_lat`, `gr_1_lon`) and `city` 
    to resolve products, and does not require a hardcoded `store_id`.
    """
    return "Not Required (Blinkit uses lat/lon directly via cookies)"

async def main():
    parser = argparse.ArgumentParser(description="Fetch Store IDs for Zepto, Instamart, and Blinkit")
    parser.add_argument("--lat", type=float, required=True, help="Latitude")
    parser.add_argument("--lng", type=float, required=True, help="Longitude")
    parser.add_argument("--pincode", type=str, required=True, help="Pincode")
    args = parser.parse_args()

    print(f"Fetching store information for:")
    print(f"Lat: {args.lat}, Lng: {args.lng}, Pincode: {args.pincode}\n")

    # 1. Fetch Blinkit
    blinkit_info = get_blinkit_store_id(args.lat, args.lng, args.pincode)
    print(f"Blinkit Store ID: {blinkit_info}")

    # 2. Fetch Zepto
    print("Fetching Zepto Store ID... (this may take a few seconds)")
    zepto_store_id = await get_zepto_store_id(args.lat, args.lng, args.pincode)
    if zepto_store_id:
        print(f"=> SUCCESS! Zepto Store ID: {zepto_store_id}\n")
    else:
        print("=> FAILED to find Zepto Store ID.\n")

    # 3. Fetch Instamart
    print("Fetching Instamart Store ID... (this may take a few seconds)")
    instamart_store_id = await get_instamart_store_id(args.lat, args.lng, args.pincode)
    if instamart_store_id:
        print(f"=> SUCCESS! Instamart Store ID: {instamart_store_id}\n")
    else:
        print("=> FAILED to find Instamart Store ID.")
        print("   Swiggy often requires manual address selection via their UI.")
        print("   If this fails, manually inspect network requests on swiggy.com/instamart.\n")

if __name__ == "__main__":
    asyncio.run(main())
