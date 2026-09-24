"""Run with: python backend/test_instamart_api_scraper.py"""

import asyncio
import json
from urllib.parse import unquote

from instamart.api_scraper import (
    INITIAL_STATE_MARKER,
    InstamartApiScraper,
    _initial_state,
    _location_cookie,
    _mapping_from_initial_state,
)
from instamart.locations import LOCATIONS
from utils.scrape_helpers import INSTAMART_CITIES


PRODUCT_ID = "DOW7FSFXZN"
SPIN_ID = "R9NFP1573Q"
FALLBACK_ID = "IJR0P0WFT8"
FALLBACK_SPIN_ID = "ABC123SPIN"


def product_payload(in_stock=False, is_available=True, product_id=PRODUCT_ID, spin_id=SPIN_ID):
    return {
        "statusCode": 0,
        "data": {
            "item": {
                "productId": product_id,
                "displayName": "Wooden spatula set",
                "inStock": in_stock,
                "isAvail": is_available,
                "variations": [{
                    "spinId": spin_id,
                    "skuId": "30BW5GX4XV",
                    "displayName": "Wooden spatula set",
                    "price": {
                        "offerPrice": {"units": "289", "nanos": 0},
                        "mrp": {"units": "899", "nanos": 0},
                    },
                    "inventory": {"inStock": in_stock},
                    "slotInfo": {"isAvail": is_available},
                }],
            }
        },
    }


async def main():
    assert [loc["name"] for loc in LOCATIONS] == INSTAMART_CITIES
    assert len(LOCATIONS) == 9 and all(loc["store_id"] for loc in LOCATIONS)

    cookie_value = json.loads(unquote(_location_cookie(LOCATIONS[0])))
    assert cookie_value["lat"] == LOCATIONS[0]["lat"]
    state = {
        "storeDetailsV2": {"storeId": "fallback-store"},
        "productV2": {"itemData": product_payload()["data"]["item"]},
    }
    parsed = _initial_state(f"<script>{INITIAL_STATE_MARKER}{json.dumps(state)};</script>")
    assert _mapping_from_initial_state(parsed, "fallback-store")["spin_id"] == SPIN_ID
    assert _mapping_from_initial_state(parsed, "wrong-store") is None

    cookie_scraper = InstamartApiScraper(browser_manager=None)
    bootstraps = 0

    async def fake_bootstrap():
        nonlocal bootstraps
        bootstraps += 1
        await asyncio.sleep(0)
        return {"sid": "test"}

    cookie_scraper._bootstrap_cookies = fake_bootstrap
    await asyncio.gather(*(cookie_scraper._ensure_cookies() for _ in range(20)))
    assert bootstraps == 1

    scraper = InstamartApiScraper(browser_manager=None)
    calls = []

    async def fake_request(url, store_id):
        calls.append((url, store_id))
        if "/widgets" in url:
            return product_payload(), 200
        if store_id == "available-store":
            return product_payload(in_stock=True), 200
        if store_id == "sold-out-store":
            return product_payload(in_stock=False), 200
        return {"statusCode": 1, "data": None}, 200

    scraper._request_json = fake_request
    locations = [
        {"name": "Available", "store_id": "available-store"},
        {"name": "Sold Out", "store_id": "sold-out-store"},
        {"name": "Unavailable", "store_id": "unavailable-store"},
    ]
    matrix = await scraper.scrape_pairs([(PRODUCT_ID, loc) for loc in locations])

    assert sum("/widgets" in url for url, _ in calls) == 1
    assert matrix[PRODUCT_ID]["Available"]["status"] == "available"
    assert matrix[PRODUCT_ID]["Sold Out"]["status"] == "out_of_stock"
    assert matrix[PRODUCT_ID]["Sold Out"]["price"] == 289
    assert matrix[PRODUCT_ID]["Unavailable"]["status"] == "unavailable"

    fallback_scraper = InstamartApiScraper(browser_manager=None)
    fallback_calls = []

    async def fake_fallback_request(url, store_id):
        fallback_calls.append((url, store_id))
        if "/widgets" in url:
            return {"statusCode": 1, "data": None}, 200
        return product_payload(
            in_stock=True, product_id=FALLBACK_ID, spin_id=FALLBACK_SPIN_ID
        ), 200

    async def fake_document(product_id, loc):
        return {
            "spin_id": FALLBACK_SPIN_ID,
            "sku_id": "fallback-sku",
            "title": "Fallback product",
        } if loc["store_id"] == "sold-out-store" else None

    fallback_scraper._request_json = fake_fallback_request
    fallback_scraper._resolve_from_document = fake_document
    fallback_matrix = await fallback_scraper.scrape_pairs(
        [(FALLBACK_ID, loc) for loc in locations]
    )
    assert sum("/widgets" in url for url, _ in fallback_calls) == len(locations)
    assert any(FALLBACK_SPIN_ID in url for url, _ in fallback_calls)
    assert fallback_matrix[FALLBACK_ID]["Available"]["status"] == "available"

    invalid = await scraper.scrape_pairs([("bad", locations[0])])
    assert invalid["BAD"]["Available"]["status"] == "invalid_format"
    print("instamart API scraper checks passed")


if __name__ == "__main__":
    asyncio.run(main())
