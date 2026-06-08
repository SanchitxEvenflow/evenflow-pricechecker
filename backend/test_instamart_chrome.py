import sys
from curl_cffi import requests
from proxy.manager import ProxyManager

def test_chrome_fingerprint():
    pm = ProxyManager("proxies.txt")
    proxy = pm.get_proxy()
    print("Using proxy:", proxy)
    
    session = requests.Session(
        impersonate="chrome124", 
        proxies={"http": proxy, "https": proxy} if proxy else None
    )
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "content-type": "application/json",
        "x-build-version": "2.347.0",
        "x-device-id": "12345678-1234-1234-1234-123456789012",
        "Referer": "https://www.swiggy.com/instamart",
    }
    
    # Also we need deviceId cookie
    cookies = {
        "_device_id": "12345678-1234-1234-1234-123456789012",
        "deviceId": "s%3A12345678-1234-1234-1234-123456789012.dummy",
    }
    session.cookies.update(cookies)
    
    api_url = "https://www.swiggy.com/api/instamart/item/v2/54ZJRDYZYL/widgets?storeId=1404766&primaryStoreId=1404766"
    res = session.get(api_url, headers=headers, timeout=10)
    print("Status:", res.status_code)
    print("Content length:", len(res.content))
    if res.status_code != 200:
        print("Response:", res.text[:200])

if __name__ == "__main__":
    test_chrome_fingerprint()
