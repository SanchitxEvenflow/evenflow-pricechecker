import sys
from curl_cffi import requests
from proxy.manager import ProxyManager

def test_safari():
    pm = ProxyManager("proxies.txt")
    proxy = pm.get_proxy()
    
    session = requests.Session(
        impersonate="safari15_5", 
        proxies={"http": proxy, "https": proxy} if proxy else None
    )
    
    url = "https://www.swiggy.com/instamart/item/54ZJRDYZYL"
    cookies = {
        "lat": "18.570437",
        "lng": "73.908812",
        "storeId": "1389691"
    }
    
    try:
        res = session.get(url, cookies=cookies, timeout=10)
        print("Status:", res.status_code)
        if "AWS WAF" in res.text or "challenge.js" in res.text:
            print("WAF Challenge detected")
        else:
            print("Passed WAF!")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    for i in range(3):
        print(f"Test {i+1}...")
        test_safari()
