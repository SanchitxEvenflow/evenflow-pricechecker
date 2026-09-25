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

    retry_scraper = InstamartApiScraper(browser_manager=None)
    retry_scraper._spin_cache[PRODUCT_ID] = {"spin_id": SPIN_ID, "sku_id": None, "title": None}
    refreshes = []
    spin_calls = []

    async def fake_refresh(generation=None):
        refreshes.append(generation)

    async def flaky_request(url, store_id):
        spin_calls.append(url)
        if len(spin_calls) == 1:
            raise RuntimeError("Instamart app-level statusCode 429 (rate limited)")
        return product_payload(in_stock=True), 200

    retry_scraper._refresh_cookies = fake_refresh
    retry_scraper._request_json = flaky_request
    retried = await retry_scraper.scrape_pairs([(PRODUCT_ID, locations[0])])
    assert retried[PRODUCT_ID]["Available"]["status"] == "available"
    assert len(refreshes) == 1 and len(spin_calls) == 2

    page_scraper = InstamartApiScraper(browser_manager=None)
    page_scraper._spin_cache[PRODUCT_ID] = {"spin_id": SPIN_ID, "sku_id": None, "title": None}

    async def rejected_spin(url, store_id):
        if store_id != "available-store":
            return {"statusCode": 1, "data": None}, 200
        payload = product_payload(in_stock=False, is_available=False)
        del payload["data"]["item"]["variations"][0]["price"]
        return payload, 200

    async def page_state(product_id, loc):
        if loc["store_id"] != "available-store":
            return None
        item = product_payload(in_stock=False)["data"]["item"]
        return {"storeDetailsV2": {"storeId": "available-store"}, "productV2": {"itemData": item}}

    page_scraper._request_json = rejected_spin
    page_scraper._fetch_document_state = page_state
    paged = await page_scraper.scrape_pairs([(PRODUCT_ID, loc) for loc in locations[:2]])
    assert paged[PRODUCT_ID]["Available"]["status"] == "out_of_stock"
    assert paged[PRODUCT_ID]["Available"]["price"] == 289
    assert paged[PRODUCT_ID]["Sold Out"]["status"] == "unavailable"

    budget_scraper = InstamartApiScraper(browser_manager=None)
    budget_scraper.cookie_budget = 2
    budget_scraper._cookies = {"s": "0"}
    sent_with = []

    async def rotate(generation=None):
        budget_scraper._cookie_generation += 1
        budget_scraper._cookie_uses = 0
        budget_scraper._cookies = {"s": str(budget_scraper._cookie_generation)}

    class FakeHttp:
        async def get(self, url, cookies, **kwargs):
            sent_with.append(cookies["s"])

    budget_scraper._refresh_cookies = rotate
    budget_scraper._http = lambda: FakeHttp()
    for _ in range(5):
        await budget_scraper._send("u")
    assert sent_with == ["0", "0", "1", "1", "2"], sent_with

    invalid = await scraper.scrape_pairs([("bad", locations[0])])
    assert invalid["BAD"]["Available"]["status"] == "invalid_format"
    print("instamart API scraper checks passed")


if __name__ == "__main__":
    asyncio.run(main())
