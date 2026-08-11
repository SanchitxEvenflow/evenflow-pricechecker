"""
zepto/scraper.py
Field-mapping for Zepto's product JSON (BFF response shape).

The old curl_cffi-based fetch_zepto_data() here is gone: Zepto's BFF
(bff-gateway.zepto.com) sits behind AWS WAF, which returns HTTP 202 with an
x-amzn-waf-action: challenge header to every server-side request regardless
of proxy/IP — it's a JS-execution challenge, not IP reputation, so no amount
of proxy rotation can pass it. See zepto/browser_scraper.py for the real
scraper: it drives a Playwright browser (which solves the JS challenge) and
extracts this exact JSON shape from the rendered page HTML, reusing
_extract_zepto_product() below.
"""

import logging

logger = logging.getLogger(__name__)


def _extract_zepto_product(json_data: dict) -> dict:
    """
    Extract product details from Zepto's PDP (v2/get_page) JSON shape.

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
