"""
zepto/scraper.py
HTTP Client using curl_cffi for Zepto's BFF API.
Mirrors the blinkit scraper structure: routes through Snowpad SOCKS5, retry logic.
"""

import logging
import os
import uuid
from datetime import datetime, timezone, timedelta

from curl_cffi import requests
from curl_cffi.requests.errors import RequestsError

from proxy.socks5_provider import get_provider as get_snowpad_provider

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# -- Config -------------------------------------------------------------------

ZEPTO_BFF_URL = os.getenv("ZEPTO_BFF_URL", "https://bff-gateway.zepto.com")

# Headers reverse-engineered from the real Zepto web app (Firefox on Windows).
# The domain changed from zeptonow.com -> zepto.com.
BROWSER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Origin": "https://www.zepto.com",
    "Referer": "https://www.zepto.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Connection": "keep-alive",
    # -- Zepto-specific routing headers (required to pass CloudFront WAF) --
    "platform": "WEB",
    "app_version": "16.0.4",
    "appVersion": "16.0.4",
    "tenant": "ZEPTO",
    "app_sub_platform": "WEB",
    "auth_revamp_flow": "v2",
    "source": "DIRECT",
    "location_type": "USER_SELECTED",
    "marketplace_type": "B2C",
    "auth_from_cookie": "true",
    "compatible_components": (
        "SWAP_AND_SAVE_ON_CART,EXTERNAL_COUPONS,BUNDLE,MULTI_SELLER_ENABLED,"
        "ROLLUPS,SCHEDULED_DELIVERY,OTOF,ROLLUPS_UOM,HOMEPAGE_V2,NEW_ETA_BANNER,"
        "VERTICAL_FEED_PRODUCT_GRID,AUTOSUGGESTION_PAGE_ENABLED,AUTOSUGGESTION_PIP,"
        "AUTOSUGGESTION_AD_PIP,BOTTOM_NAV_FULL_ICON,NEW_ROLLUPS_ENABLED,"
        "RERANKING_QCL_RELATED_PRODUCTS,RE_PROMISE_ETA_ORDER_SCREEN_ENABLED,"
        "NEW_BILL_INFO,COUPON_WIDGET_CART_REVAMP,DELIVERY_UPSELLING_WIDGET,"
        "ZEPTO_PASS:5,MARKETPLACE_REPLACEMENT,PLP_ON_SEARCH,"
        "PAAN_BANNER_WIDGETIZED,DYNAMIC_FILTERS,PHARMA_ENABLED,SUPERSTORE_V1,"
        "CART_REDESIGN_ENABLED,IS_DYNAMIC_NZS_SUPPORTED,"
        "MANUALLY_APPLIED_DELIVERY_FEE_RECEIVABLE,AUTOSUGGESTION_RECIPE_PIP,"
        "SHIPMENT_WIDGETIZATION_ENABLED,SEARCH_FILTERS_V1,"
        "QUERY_DESCRIPTION_WIDGET,MEDS_WITH_SIMILAR_SALT_WIDGET,"
        "MARKETPLACE_CATEGORY_GRID,OOS_RECOMMENDATIONS,TABBED_CAROUSEL_V2,"
        "GIFT_CARD,PROMO_CASH:0,PHARMACY_ENABLED,L4_ATTRIBUTES_ENABLED,"
        "RECOMMENDED_COUPON_WIDGET,ITEMISATION_ENABLED,TRUSTMARKER_V2,"
        "24X7_ENABLED_V1,SCLP_ADD_MONEY,JUSPAY_CARDS_BLOCK,"
        "NO_PLATFORM_CHECK_ENABLED_V2,SUPER_SAVER:0,OFSE,GIFTING_ENABLED,"
        "HP_V4_FEED,SIZE_CHART_PDP,WIDGET_BASED_ETA,PC_REVAMP_1,NO_COST_EMI_V1,"
        "PRE_SEARCH,WIDGET_RESTRUCTURE,PRICING_CAMPAIGN_ID,BACHAT_FOR_ALL,"
        "TABBED_CAROUSEL_V3,CART_LMS:1,CART_LMS:2,SAMPLING_UPSELL_CAMPAIGN,"
        "UPSELL_COUPON_SS:0,DISCOUNTED_ADDONS_ENABLED,SIZE_EXCHANGE_ENABLED,"
        "ENABLE_FLOATING_CART_BUTTON,IPP_ENABLED,FILTER_ATTRIBUTES,LMS_BROWSE,"
        "SAMPLING_V3,HYBRID_CAMPAIGN,MILESTONE_CAMPAIGN,SEARCH_RELOOK,"
        "MERGE_CONFIG_STORE_DETAIL,SEARCH_PRODUCT_GRID_V2,"
        "L3_UNDERSTANDING_LAYOUT,FASHION_REVAMP,MULTITAB_V2,"
        "INTERACTIVE_BANNER_GRID,CUSTOMIZATION_ENABLED"
    ),
}


# -- Extraction Helpers -------------------------------------------------------

def _extract_zepto_product(json_data: dict) -> dict:
    """
    Extract product details from Zepto's PDP (v2/get_page) JSON response.

    The response nests product info at:
        pageLayout.pageData.productInfo
            .product        -> name, brand
            .storeProduct   -> discountedSellingPrice, mrp, outOfStock
    Prices are returned in **paise** (e.g. 91000 = Rs 910).
    """
    try:
        product_info = json_data["pageLayout"]["pageData"]["productInfo"]
        product = product_info.get("product", {})
        store_product = product_info.get("storeProduct", {})

        title = product.get("name") or "Unknown Product"
        brand = product.get("brand")
        if brand and title and not title.lower().startswith(brand.lower()):
            title = f"{brand} {title}"

        # Prices are in paise
        raw_price = store_product.get("discountedSellingPrice") or store_product.get("superSaverSellingPrice")
        raw_mrp = store_product.get("mrp")

        price = round(float(raw_price) / 100, 2) if raw_price else None
        mrp = round(float(raw_mrp) / 100, 2) if raw_mrp else None

        out_of_stock = store_product.get("outOfStock", False)
        status = "out_of_stock" if out_of_stock else "available"

        return {
            "title": title,
            "price": price,
            "mrp": mrp,
            "status": status,
            "is_sold_out": out_of_stock,
        }
    except (KeyError, TypeError) as e:
        # Fallback: the response structure was unexpected
        logger.warning("[Zepto] Extraction fallback triggered: %s", e)
        return {
            "title": "Unknown Product",
            "price": None,
            "mrp": None,
            "status": "error",
            "is_sold_out": False,
        }


# -- Main fetch function -----------------------------------------------------

def fetch_zepto_data(
    item_id: str,
    pincode: str,
    lat: float,
    lon: float,
    city: str,
    store_id: str,
    fallback_title: str | None = None,
    fallback_mrp: float | None = None,
) -> dict:
    """
    Fetch product data from Zepto's PDP endpoint.

    Uses the v2/get_page endpoint with page_type=PDP and the product_variant_id
    query parameter, matching the real Zepto web app behaviour.

    Retries up to 3 times on a fresh Snowpad SOCKS5 IP on block/error. No
    direct-connection fallback — protects the local/home IP from Zepto's WAF.

    This is a synchronous function (curl_cffi).
    """
    product_url = f"https://www.zepto.com/pn/product/{item_id}"
    now = datetime.now(IST).isoformat()

    def _error_result(msg: str = "error") -> dict:
        return {
            "product_id": item_id,
            "city": city,
            "title": None,
            "price": None,
            "mrp": None,
            "status": "error",
            "is_sold_out": False,
            "url": product_url,
            "checked_at": now,
            "error_message": msg,
        }

    logger.info("[Zepto] %s: fetching item=%s, store=%s", city, item_id, store_id)

    if store_id == "TODO" or not store_id:
        logger.warning("[Zepto] %s: SKIPPED — store_id not configured in locations.py", city)
        return _error_result("missing_store_id")

    import urllib.parse

    # Reduced retries since the proxy pool is being hard-blocked by Zepto
    # If we have a CF Worker, we can retry multiple times safely.
    cf_worker_url = os.getenv("ZEPTO_CLOUDFLARE_WORKER_URL", "")
    has_cf_worker = bool(cf_worker_url)

    snowpad = get_snowpad_provider()
    use_snowpad = snowpad.enabled
    if has_cf_worker:
        max_attempts = 3
    elif use_snowpad:
        max_attempts = 3
    else:
        logger.warning("[Zepto] %s: no CF worker and Snowpad disabled — cannot scrape", city)
        return _error_result("no_proxy_available")

    import time
    import random
    time.sleep(random.uniform(0.5, 1.5))

    for attempt in range(max_attempts + 1):  # +1 = direct-connection fallback (or direct worker)
        proxy = None

        if has_cf_worker:
            # When using CF Worker, we don't need a Snowpad proxy
            proxy = None
        else:
            if attempt < max_attempts:
                proxy = snowpad.curl_url()
            elif attempt == max_attempts:
                # Prevent fallback to home IP as requested
                logger.info("[Zepto] %s: skipping direct connection to protect local IP.", city)
                break

        proxies = {"http": proxy, "https": proxy} if proxy else None
        session = requests.Session(impersonate="chrome131", proxies=proxies, verify=False)

        try:
            # Build per-request IDs (mimic browser behaviour)
            device_id = str(uuid.uuid4())
            session_id = str(uuid.uuid4())
            request_id = str(uuid.uuid4())

            headers = BROWSER_HEADERS.copy()
            headers.update({
                "storeId": store_id,
                "store_id": store_id,
                "store_ids": store_id,
                "deviceId": device_id,
                "device_id": device_id,
                "sessionId": session_id,
                "session_id": session_id,
                "requestId": request_id,
                "request_id": request_id,
            })

            # Build the PDP URL exactly as the real web app does
            base_url = (
                f"{ZEPTO_BFF_URL}/lms/api/v2/get_page"
                f"?store_id={store_id}"
                f"&page_type=PDP"
                f"&version=v3"
                f"&latitude={lat}"
                f"&longitude={lon}"
                f"&show_new_eta_banner=false"
                f"&page_size=5"
                f"&product_variant_id={item_id}"
            )
            
            prod_url = f"{base_url}&fallback_enabled=false"
            
            # Route through Cloudflare Worker if configured
            final_url = prod_url
            if has_cf_worker:
                final_url = f"{cf_worker_url}?url={urllib.parse.quote(prod_url)}"

            logger.info("[Zepto] %s: GET %s... (attempt %d/%d)", city, prod_url[:120], attempt + 1, max_attempts + 1)
            response = session.get(final_url, headers=headers, timeout=15)

            logger.info("[Zepto] %s: HTTP %d (%d bytes)", city, response.status_code, len(response.content))

            if response.status_code in (401, 403, 427, 429, 451):
                logger.warning("Blocked (HTTP %d) for item_id=%s city=%s", response.status_code, item_id, city)
                if use_snowpad and not has_cf_worker:
                    snowpad.report_failure()
                if attempt < max_attempts:
                    if response.status_code == 429:
                        time.sleep(1.0)
                    continue
                return _error_result(f"blocked_{response.status_code}")

            if response.status_code == 404:
                logger.warning("Item %s not found/unserviceable in %s", item_id, city)
                if use_snowpad and not has_cf_worker:
                    snowpad.report_success()
                return {
                    "product_id": item_id,
                    "city": city,
                    "title": None,
                    "price": None,
                    "mrp": None,
                    "status": "not_found",
                    "is_sold_out": True,
                    "url": product_url,
                    "checked_at": now,
                    "error_message": None,
                }

            if response.status_code != 200:
                logger.error("Zepto returned status %d for item_id=%s city=%s", response.status_code, item_id, city)
                logger.debug("[Zepto] %s: Response snippet: %s", city, response.text[:300])
                if use_snowpad and not has_cf_worker:
                    snowpad.report_failure()
                if attempt < max_attempts:
                    continue
                return _error_result(f"http_{response.status_code}")

            try:
                json_data = response.json()
            except ValueError as e:
                logger.error("[Zepto] %s: invalid JSON: %s", city, response.text[:300])
                raise e

            # If the product isn't found in the local store, try with fallback to get the price
            if json_data.get("code") == 5 or not json_data.get("pageLayout"):
                if fallback_title is not None:
                    # We already know the title and mrp from a previous city scrape!
                    logger.info("[Zepto] %s: not in local store, using provided fallback_title", city)
                    if use_snowpad and not has_cf_worker:
                        snowpad.report_success()
                    return {
                        "product_id": item_id,
                        "city": city,
                        "title": fallback_title,
                        "price": None,
                        "mrp": fallback_mrp,
                        "status": "out_of_stock",
                        "is_sold_out": True,
                        "url": product_url,
                        "checked_at": now,
                        "error_message": None,
                    }

                logger.info("[Zepto] %s: not in local store, retrying with fallback", city)
                fallback_url = f"{base_url}&fallback_enabled=True"
                response = session.get(fallback_url, headers=headers, timeout=15)
                json_data = response.json()

                if json_data.get("code") == 5 or not json_data.get("pageLayout"):
                    logger.info("[Zepto] %s: fallback also returned no product data", city)
                    if use_snowpad and not has_cf_worker:
                        snowpad.report_success()
                    return _error_result("not_in_any_store")

                # Mark as out of stock since we had to fallback
                try:
                    sp = json_data["pageLayout"]["pageData"]["productInfo"]["storeProduct"]
                    sp["outOfStock"] = True
                except KeyError:
                    pass

            # Extract product data
            product = _extract_zepto_product(json_data)
            logger.info("[Zepto] %s: OK — %s = Rs.%s", city, product['title'], product['price'])

            if use_snowpad and not has_cf_worker:
                snowpad.report_success()

            return {
                "product_id": item_id,
                "city": city,
                "title": product["title"],
                "price": product["price"],
                "mrp": product["mrp"],
                "status": product["status"],
                "is_sold_out": product["is_sold_out"],
                "url": product_url,
                "checked_at": now,
            }

        except (RequestsError, TimeoutError) as e:
            logger.error("[Zepto] %s: network/timeout error on attempt %d for item_id=%s: %s", city, attempt + 1, item_id, e)
            if use_snowpad and not has_cf_worker:
                snowpad.report_failure()
            if attempt < max_attempts:
                continue
            return _error_result(f"network_error: {e}")

        except ValueError as e:
            logger.error("JSON/extraction error on attempt %d for item_id=%s: %s", attempt + 1, item_id, e)
            if "response" in locals():
                text = response.text.lower()
                if "cloudflare" in text or "<html" in text:
                    logger.error("Cloudflare challenge detected -- rotate proxies")
                    if use_snowpad and not has_cf_worker:
                        snowpad.report_failure()
                    if attempt < max_attempts:
                        continue
            return _error_result(f"extraction_error: {e}")

        except Exception as e:
            logger.error("[Zepto] %s: unexpected error on attempt %d for item_id=%s: %s", city, attempt + 1, item_id, e)
            if use_snowpad and not has_cf_worker:
                snowpad.report_failure()
            if attempt < max_attempts:
                continue
            return _error_result(f"unexpected: {e}")

        finally:
            session.close()

    return _error_result("max_retries_exceeded")