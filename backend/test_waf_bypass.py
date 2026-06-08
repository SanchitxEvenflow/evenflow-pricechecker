from curl_cffi import requests
import sys

def test_waf_bypass(token):
    url = "https://www.swiggy.com/instamart/item/54ZJRDYZYL"
    cookies = {
        "lat": "18.570437", 
        "lng": "73.908812", 
        "storeId": "1389691",
        "aws-waf-token": token
    }
    
    session = requests.Session(impersonate="chrome124")
    res = session.get(url, cookies=cookies, timeout=10)
    print("Status:", res.status_code)
    
    if "AWS WAF" in res.text or "challenge.js" in res.text:
        print("WAF Challenge detected EVEN WITH TOKEN!")
    else:
        print("Passed WAF with token!!")

if __name__ == "__main__":
    test_waf_bypass(sys.argv[1])
