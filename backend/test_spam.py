import time
import random
from curl_cffi import requests

def test_direct_spam():
    url = "https://www.swiggy.com/instamart/item/54ZJRDYZYL"
    cookies = {"lat": "18.570437", "lng": "73.908812", "storeId": "1389691"}
    
    session = requests.Session(impersonate="chrome124")
    
    for i in range(8):
        # time.sleep(random.uniform(0.5, 1.5))
        res = session.get(url, cookies=cookies, timeout=10)
        print(f"Req {i+1}: Status {res.status_code}", end=" ")
        if "AWS WAF" in res.text or "challenge.js" in res.text:
            print("- WAF Blocked!")
        else:
            print("- Passed!")

if __name__ == "__main__":
    test_direct_spam()
