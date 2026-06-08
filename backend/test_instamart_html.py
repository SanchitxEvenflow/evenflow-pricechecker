import sys
from curl_cffi import requests
from proxy.manager import ProxyManager

def test_html():
    pm = ProxyManager("proxies.txt")
    proxy = pm.get_proxy()
    
    session = requests.Session(
        impersonate="chrome124", 
        proxies={"http": proxy, "https": proxy} if proxy else None
    )
    
    url = "https://www.swiggy.com/instamart/item/54ZJRDYZYL"
    res = session.get(url, timeout=10)
    print("Status:", res.status_code)
    
    # check if schema is in it
    import re
    schema_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', res.text, re.DOTALL)
    if schema_match:
        print("Schema found!")
        print(schema_match.group(1)[:100])
    else:
        print("No schema found.")
        print("Response:", res.text[:200])

if __name__ == "__main__":
    test_html()
