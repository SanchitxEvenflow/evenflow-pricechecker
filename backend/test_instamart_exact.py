import sys
from curl_cffi import requests

def test_swiggy():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:151.0) Gecko/20100101 Firefox/151.0",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Referer": "https://www.swiggy.com/instamart/item/54ZJRDYZYL",
        "content-type": "application/json",
        "matcher": "gf7g78ef7g777b7bd8ebfdc",
        "x-build-version": "2.347.0",
        "x-device-id": "bf7bcdac-d2f9-4886-9f98-33afdc5acb90",
        "Connection": "keep-alive",
        "Cookie": "deviceId=s%3Abf7bcdac-d2f9-4886-9f98-33afdc5acb90.MgyKblRrbRIffRNDG2azncZk78q8ovfLEVH24%2BKRdJ0; tid=eyJLSUQiOiIyIiwiYWxnIjoiSFMyNTYiLCJ0eXAiOiJKV1QifQ.eyJleHAiOjE3ODA5MDI0NDcsImlhdCI6MTc4MDg5ODg0Nywic2Vzc2lvbl9kYXRhIjoic0wycldYakhXZUhUcTNab2pabStDdHhTeFJ5aHRZT2VpMGFaQWY2UUp3WjRybmJNVGQyckoyMjEzWW9JcXludFUvd1FIejJSblFwaEJWTGJDNUcxZWFTNnJhYzVjbkRhZ1RMTTdnc2gycEdFMjE3emkwTzNuTVdpblRnV1FQZ3k1eUMyT2crVWhIN1doaURURlhtU3lCVlhKbTl5aVJtYlFvZFJQYXBISE9FQS91RmFFNVhWM3EvWkg",
    }
    
    print("\nHitting API with user's exact headers...")
    api_url = "https://www.swiggy.com/api/instamart/item/v2/54ZJRDYZYL/widgets?storeId=1404766&primaryStoreId=1404766&secondaryStoreId="
    
    # Notice we don't impersonate, or maybe we impersonate the matching browser. The user agent is Firefox 151
    # curl_cffi doesn't have firefox151, we can just use normal requests for a second to test if it's purely header-based.
    import requests as normal_requests
    res2 = normal_requests.get(api_url, headers=headers, timeout=10)
    print("Normal requests status:", res2.status_code)
    print("Normal requests Content len:", len(res2.content))
    if res2.status_code == 200:
        print("Success!", res2.json().get('statusMessage'))
    else:
        print("Failed normal requests:", res2.text[:200])

    # Now test with curl_cffi
    session = requests.Session(impersonate="firefox133")
    res3 = session.get(api_url, headers=headers, timeout=10)
    print("\nCurl_cffi status:", res3.status_code)
    print("Curl_cffi Content len:", len(res3.content))
    if res3.status_code == 200:
        print("Success!", res3.json().get('statusMessage'))
    else:
        print("Failed curl_cffi:", res3.text[:200])

if __name__ == "__main__":
    test_swiggy()
