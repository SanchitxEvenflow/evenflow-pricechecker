import pytest
from zepto.scraper import fetch_zepto_data

def test_zepto_fetch_chennai():
    """Test with the real Chennai store_id and product_variant_id from the curl command."""
    res = fetch_zepto_data(
        item_id="b998bfa8-0380-400e-877b-8d7b7b30bb92",
        pincode="600119",
        lat=12.857688,
        lon=80.232062,
        city="Chennai",
        store_id="7cc8853d-4ba2-4537-808d-95a7adfcf500",
        proxy_manager=None
    )
    print("Zepto fetch result:", res)
    assert res is not None
    assert "status" in res
