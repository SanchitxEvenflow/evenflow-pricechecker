import sys
from curl_cffi import requests

def test_headers():
    url = "https://www.swiggy.com/instamart/item/54ZJRDYZYL"
    cookies = {"lat": "18.570437", "lng": "73.908812", "storeId": "1389691"}
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }
    
    session = requests.Session(impersonate="chrome124")
    res = session.get(url, headers=headers, cookies=cookies, timeout=10)
    print("Status:", res.status_code)
    
    if "AWS WAF" in res.text or "challenge.js" in res.text:
        print("WAF Challenge detected!")
    else:
        print("Passed WAF!")

if __name__ == "__main__":
    test_headers()
