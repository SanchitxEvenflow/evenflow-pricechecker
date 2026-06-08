import sys
from curl_cffi import requests

def test_swiggy():
    session = requests.Session(impersonate="chrome124")
    
    # 1. Get homepage to get cookies
    print("Getting homepage...")
    res = session.get("https://www.swiggy.com/", timeout=10)
    print("Status:", res.status_code)
    print("Cookies:", session.cookies.get_dict())
    
    # 2. Extract deviceId
    cookies = session.cookies.get_dict()
    device_id_raw = cookies.get("_device_id", "")
    print("Extracted _device_id:", device_id_raw)
    
    # 3. Hit instamart API
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "content-type": "application/json",
        "matcher": "gf7g78ef7g777b7bd8ebfdc",
        "x-build-version": "2.347.0",
        "x-device-id": device_id_raw,
        "Referer": "https://www.swiggy.com/instamart/item/54ZJRDYZYL",
    }
    
    print("\nHitting API...")
    api_url = "https://www.swiggy.com/api/instamart/item/v2/54ZJRDYZYL/widgets?storeId=1404766&primaryStoreId=1404766&secondaryStoreId="
    res2 = session.get(api_url, headers=headers, timeout=10)
    print("Status:", res2.status_code)
    print("Content len:", len(res2.content))
    if res2.status_code != 200:
        print(res2.text[:500])

if __name__ == "__main__":
    test_swiggy()
