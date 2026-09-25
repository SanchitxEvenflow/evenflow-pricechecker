"""Fast Instamart price scraper: one browser cookie session, pooled API calls."""

import asyncio
import json
import logging
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import quote

from curl_cffi.requests import AsyncSession

from proxy.socks5_provider import get_provider as get_snowpad_provider

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
BASE_URL = "https://instamart.in"
ITEM_URL = f"{BASE_URL}/item/{{product_id}}"
WIDGETS_URL = f"{BASE_URL}/api/instamart/item/v2/{{product_id}}/widgets"
SPIN_URL = f"{BASE_URL}/api/instamart/item/v2/spin/{{spin_id}}"
PRODUCT_ID_RE = re.compile(r"^[A-Z0-9]{10}$")
INITIAL_STATE_MARKER = "window.___INITIAL_STATE___ = "

_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-IN,en;q=0.9",
    "referer": f"{BASE_URL}/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def _find_product(payload: dict, product_id: str) -> dict | None:
    return next((obj for obj in _objects(payload) if obj.get("productId") == product_id), None)


def _money(value) -> float | None:
    if not isinstance(value, dict):
        return None
    try:
        amount = float(value.get("units", 0)) + float(value.get("nanos", 0)) / 1_000_000_000
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _variation(product: dict, spin_id: str | None = None) -> dict:
    variations = product.get("variations") or []
    if spin_id:
        match = next((item for item in variations if item.get("spinId") == spin_id), None)
        if match:
            return match
    return variations[0] if variations else {}


def _product_values(product: dict, spin_id: str | None = None) -> dict:
    variant = _variation(product, spin_id)
    price = variant.get("price") or {}
    inventory = variant.get("inventory") or {}
    slot = variant.get("slotInfo") or {}
    in_stock = inventory.get("inStock", product.get("inStock"))
    is_available = slot.get("isAvail", product.get("isAvail"))
    return {
        "title": variant.get("displayName") or product.get("displayName"),
        "spin_id": variant.get("spinId") or spin_id,
        "sku_id": variant.get("skuId"),
        "price": _money(price.get("offerPrice")),
        "mrp": _money(price.get("mrp")),
        "in_stock": in_stock,
        "is_available": is_available,
    }


def _stock_status(values: dict) -> str:
    if values["in_stock"] is True and values["price"] is not None:
        return "available"
    if values["in_stock"] is False and (values["price"] is not None or values["is_available"] is True):
        return "out_of_stock"
    if values["is_available"] is False:
        return "unavailable"
    return "error"


def _cookie_dict(raw: str) -> dict[str, str]:
    cookies = {}
    for part in raw.split(";"):
        if "=" in part:
            name, value = part.strip().split("=", 1)
            if name:
                cookies[name] = value
    return cookies


def _location_cookie(loc: dict) -> str:
    """Build the location cookie used by Instamart's server-rendered item page."""
    label = loc.get("address") or loc.get("area") or loc["name"]
    value = {
        "lat": loc["lat"],
        "lng": loc["lng"],
        "address": label,
        "id": "",
        "annotation": label,
        "name": "",
    }
    return quote(json.dumps(value, separators=(",", ":")), safe="")


def _initial_state(html: str) -> dict | None:
    start = html.find(INITIAL_STATE_MARKER)
    if start < 0:
        return None
    try:
        state, _ = json.JSONDecoder().raw_decode(
            html[start + len(INITIAL_STATE_MARKER):].lstrip()
        )
    except (TypeError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def _page_product(state: dict | None, expected_store_id: str) -> dict | None:
    if not state:
        return None
    store = state.get("storeDetailsV2") or {}
    actual_store_id = store.get("storeId") or (store.get("primaryStore") or {}).get("id")
    if str(actual_store_id or "") != expected_store_id:
        return None
    return (state.get("productV2") or {}).get("itemData") or None


def _mapping_from_initial_state(state: dict | None, expected_store_id: str) -> dict | None:
    product = _page_product(state, expected_store_id)
    if not product:
        return None
    values = _product_values(product)
    if not values.get("spin_id"):
        return None
    return {
        "spin_id": values["spin_id"],
        "sku_id": values["sku_id"],
        "title": values["title"],
    }


class InstamartApiScraper:
    def __init__(self, browser_manager):
        self.browser_manager = browser_manager
        self.concurrency = max(1, int(os.getenv("INSTAMART_API_CONCURRENCY", "24")))
        self._request_sem = asyncio.Semaphore(self.concurrency)
        self._cookie_lock = asyncio.Lock()
        self._cookies: dict[str, str] = {}
        self._cookie_generation = 0
        self._cookie_uses = 0
        # Measured ~160 requests per cookie before item pages degrade; keep headroom.
        self.cookie_budget = max(1, int(os.getenv("INSTAMART_COOKIE_BUDGET", "120")))
        self._env_cookies_loaded = False
        self._session: AsyncSession | None = None
        self._spin_cache: dict[str, dict] = {}
        # One sticky Snowpad exit IP for this instance's whole lifetime — shared by
        # the Playwright cookie/JS-challenge solve AND the curl_cffi API calls,
        # since Instamart's WAF binds the challenge token to the solving IP.
        self._proxy_session_id = uuid.uuid4().hex[:8]

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        await get_snowpad_provider().close_bridge(self._proxy_session_id)

    def _http(self) -> AsyncSession:
        if self._session is None:
            snowpad = get_snowpad_provider()
            proxy = snowpad.curl_url(session_id=self._proxy_session_id) if snowpad.enabled else None
            self._session = AsyncSession(
                max_clients=self.concurrency,
                impersonate="chrome124",
                headers=_HEADERS,
                proxies={"http": proxy, "https": proxy} if proxy else None,
            )
        return self._session

    async def _bootstrap_cookies(self) -> dict[str, str]:
        if not self._env_cookies_loaded:
            self._env_cookies_loaded = True
            configured = _cookie_dict(os.getenv("INSTAMART_COOKIES", ""))
            if configured:
                logger.info("[Instamart API] Loaded cookies from INSTAMART_COOKIES")
                return configured

        if self.browser_manager is None:
            raise RuntimeError("browser pool unavailable for Instamart cookie refresh")

        snowpad = get_snowpad_provider()
        browser_proxy = await snowpad.bridge_proxy(session_id=self._proxy_session_id) if snowpad.enabled else None
        browser = await self.browser_manager.acquire()
        context = await browser.new_context(
            user_agent=_HEADERS["user-agent"], locale="en-IN", proxy=browser_proxy,
        )
        try:
            await context.route(
                re.compile(r"\.(png|jpg|jpeg|gif|webp|svg|woff2?|ttf|mp4)$", re.IGNORECASE),
                lambda route: route.abort(),
            )
            page = await context.new_page()
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(1500)
            cookies = {
                cookie["name"]: cookie["value"]
                for cookie in await context.cookies(BASE_URL)
                if cookie.get("value")
            }
            if not cookies:
                raise RuntimeError("Instamart returned no session cookies")
            logger.info("[Instamart API] Playwright cookie bootstrap succeeded (%d cookies)", len(cookies))
            return cookies
        finally:
            await context.close()

    async def _refresh_cookies(self, observed_generation: int | None = None) -> None:
        async with self._cookie_lock:
            if observed_generation is not None and observed_generation != self._cookie_generation:
                return
            cookies = await self._bootstrap_cookies()
            self._cookies = cookies
            self._cookie_generation += 1
            self._cookie_uses = 0
            if self._session is not None:
                self._session.cookies.clear()

    async def _ensure_cookies(self) -> None:
        if not self._cookies:
            await self._refresh_cookies(self._cookie_generation)

    async def _send(self, url: str, extra_cookies: dict | None = None, **kwargs):
        # Instamart's quota is per session cookie and, past it, item pages come back
        # silently empty (HTTP 200, no store, no product), so rotate before it runs out.
        async with self._request_sem:
            if self._cookie_uses >= self.cookie_budget:
                await self._refresh_cookies(self._cookie_generation)
            self._cookie_uses += 1
            generation = self._cookie_generation
            cookies = {**self._cookies, **(extra_cookies or {})}
            return generation, await self._http().get(url, cookies=cookies, timeout=20, **kwargs)

    async def _request_json(self, url: str, store_id: str) -> tuple[dict, int]:
        await self._ensure_cookies()
        refreshed = False
        last_error = "request failed"

        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                generation, response = await self._send(url, params={"storeId": store_id})
                response_cookies = response.cookies.get_dict()
                if response_cookies and generation == self._cookie_generation:
                    self._cookies.update(response_cookies)

                if response.status_code in (401, 403):
                    if refreshed:
                        raise RuntimeError(f"session rejected after refresh (HTTP {response.status_code})")
                    await self._refresh_cookies(generation)
                    refreshed = True
                    continue

                if response.status_code == 429 or response.status_code >= 500:
                    last_error = f"HTTP {response.status_code}"
                    if attempt < max_attempts - 1:
                        retry_after = response.headers.get("retry-after")
                        delay = float(retry_after) if retry_after and retry_after.isdigit() else min(0.5 * (2 ** attempt), 8)
                        await asyncio.sleep(delay + random.uniform(0, 0.25))
                        continue
                    raise RuntimeError(last_error)

                try:
                    data = response.json()
                except Exception as exc:
                    if refreshed:
                        raise RuntimeError("Instamart returned non-JSON after cookie refresh") from exc
                    await self._refresh_cookies(generation)
                    refreshed = True
                    continue

                if not isinstance(data, dict):
                    raise RuntimeError("Instamart returned an invalid JSON payload")

                if data.get("statusCode") == 429:
                    # Quota is per session cookie, so waiting never helps; mint a new one.
                    last_error = "Instamart app-level statusCode 429 (rate limited)"
                    if attempt < max_attempts - 1:
                        await self._refresh_cookies(generation)
                        continue
                    raise RuntimeError(last_error)

                return data, response.status_code
            except RuntimeError:
                raise
            except Exception as exc:
                last_error = str(exc) or type(exc).__name__
                if attempt < max_attempts - 1:
                    await asyncio.sleep(min(0.5 * (2 ** attempt), 8) + random.uniform(0, 0.25))
                    continue
                raise RuntimeError(last_error) from exc

        raise RuntimeError(last_error)

    async def _resolve_from_document(self, product_id: str, loc: dict) -> dict | None:
        """Resolve a spin ID from the SSR item state when the widgets API cannot."""
        state = await self._fetch_document_state(product_id, loc)
        return _mapping_from_initial_state(state, str(loc["store_id"]))

    async def _fetch_document_state(self, product_id: str, loc: dict) -> dict | None:
        await self._ensure_cookies()
        refreshed = False
        last_error = "document request failed"

        for attempt in range(3):
            try:
                generation, response = await self._send(
                    ITEM_URL.format(product_id=product_id),
                    extra_cookies={"userLocation": _location_cookie(loc)},
                    headers={
                        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "referer": f"{BASE_URL}/",
                    },
                )

                response_cookies = response.cookies.get_dict()
                response_cookies.pop("userLocation", None)
                self._http().cookies.delete("userLocation")
                if response_cookies and generation == self._cookie_generation:
                    self._cookies.update(response_cookies)

                if response.status_code in (401, 403):
                    if refreshed:
                        raise RuntimeError(
                            f"document session rejected after refresh (HTTP {response.status_code})"
                        )
                    await self._refresh_cookies(generation)
                    refreshed = True
                    continue

                if response.status_code == 429 or response.status_code >= 500:
                    last_error = f"document HTTP {response.status_code}"
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (2 ** attempt) + random.uniform(0, 0.25))
                        continue
                    raise RuntimeError(last_error)
                if response.status_code >= 400:
                    raise RuntimeError(f"document HTTP {response.status_code}")

                return _initial_state(response.text)
            except RuntimeError:
                raise
            except Exception as exc:
                last_error = str(exc) or type(exc).__name__
                if attempt < 2:
                    await asyncio.sleep(0.5 * (2 ** attempt) + random.uniform(0, 0.25))
                    continue
                raise RuntimeError(last_error) from exc

        raise RuntimeError(last_error)

    async def resolve_product(self, product_id: str, locations: list[dict]) -> dict | None:
        cached = self._spin_cache.get(product_id)
        if cached:
            return cached

        had_error = False
        last_error = None
        for loc in locations:
            store_id = str(loc["store_id"])
            try:
                payload, _ = await self._request_json(
                    WIDGETS_URL.format(product_id=product_id), store_id
                )
            except Exception as exc:
                last_error = exc
                had_error = True
                continue
            if payload.get("statusCode") != 0:
                continue
            product = _find_product(payload, product_id)
            if not product:
                continue
            values = _product_values(product)
            if values.get("spin_id"):
                mapping = {
                    "spin_id": values["spin_id"],
                    "sku_id": values["sku_id"],
                    "title": values["title"],
                }
                self._spin_cache[product_id] = mapping
                return mapping

        logger.info(
            "[Instamart API] %s unresolved by widgets; trying item documents",
            product_id,
        )
        for loc in locations:
            try:
                mapping = await self._resolve_from_document(product_id, loc)
            except Exception as exc:
                last_error = exc
                had_error = True
                continue
            if mapping:
                self._spin_cache[product_id] = mapping
                logger.info(
                    "[Instamart API] %s resolved from item document at store %s",
                    product_id,
                    loc["store_id"],
                )
                return mapping

        if had_error:
            raise RuntimeError(str(last_error)) from last_error
        return None

    @staticmethod
    def _result(product_id: str, loc: dict, **values) -> dict:
        result = {
            "product_id": product_id,
            "city": loc["name"],
            "title": None,
            "price": None,
            "mrp": None,
            "status": "error",
            "is_sold_out": False,
            "is_available": None,
            "in_stock": None,
            "spin_id": None,
            "sku_id": None,
            "store_id": str(loc.get("store_id") or ""),
            "http_status": None,
            "api_status": None,
            "url": ITEM_URL.format(product_id=product_id),
            "checked_at": datetime.now(IST).isoformat(),
            "error_message": None,
        }
        result.update(values)
        return result

    async def fetch_product(self, product_id: str, loc: dict, mapping: dict) -> dict:
        store_id = str(loc.get("store_id") or "")
        try:
            payload, http_status = await self._request_json(
                SPIN_URL.format(spin_id=mapping["spin_id"]), store_id
            )
        except Exception as exc:
            return self._result(
                product_id, loc, spin_id=mapping["spin_id"], sku_id=mapping.get("sku_id"),
                title=mapping.get("title"), error_message=str(exc),
            )

        api_status = payload.get("statusCode")
        fallback = dict(spin_id=mapping["spin_id"], sku_id=mapping.get("sku_id"), title=mapping.get("title"))
        values = fallback
        status = "unavailable"
        if api_status == 0:
            product = _find_product(payload, product_id)
            if not product:
                return self._result(
                    product_id, loc, **fallback, http_status=http_status, api_status=api_status,
                    error_message="product missing from spin response",
                )
            values = _product_values(product, mapping["spin_id"])
            status = _stock_status(values)

        if status == "unavailable":
            # Spin API reports some sold-out items as unavailable with no price, while the
            # item page the shopper sees still lists them as sold out with a price.
            try:
                page = _page_product(await self._fetch_document_state(product_id, loc), store_id)
            except Exception as exc:
                logger.warning("[Instamart API] %s @ %s: page fallback failed: %s", product_id, store_id, exc)
                page = None
            if page:
                page_values = _product_values(page, mapping["spin_id"])
                if _stock_status(page_values) in ("available", "out_of_stock"):
                    values, status = page_values, _stock_status(page_values)

        return self._result(
            product_id,
            loc,
            **values,
            status=status,
            is_sold_out=status == "out_of_stock",
            http_status=http_status,
            api_status=api_status,
            error_message="incomplete product state" if status == "error" else None,
        )

    async def scrape_pairs(
        self,
        pairs: list[tuple[str, dict]],
        on_result: Callable[[dict], None] | None = None,
    ) -> dict[str, dict[str, dict]]:
        """Resolve each product once, then fetch only the requested product/store pairs."""
        normalized: list[tuple[str, dict]] = []
        for raw_product_id, loc in pairs:
            product_id = raw_product_id.strip().upper()
            if product_id and loc.get("store_id"):
                normalized.append((product_id, loc))

        matrix: dict[str, dict[str, dict]] = {}
        product_ids = list(dict.fromkeys(product_id for product_id, _ in normalized))
        locations = list({str(loc["store_id"]): loc for _, loc in normalized}.values())

        async def resolve(product_id: str):
            if not PRODUCT_ID_RE.fullmatch(product_id):
                return product_id, None, "invalid product ID"
            try:
                return product_id, await self.resolve_product(product_id, locations), None
            except Exception as exc:
                return product_id, None, str(exc)

        mappings = {
            product_id: (mapping, error)
            for product_id, mapping, error in await asyncio.gather(
                *(resolve(product_id) for product_id in product_ids)
            )
        }

        tasks = []
        for product_id, loc in normalized:
            mapping, error = mappings[product_id]
            if mapping is None:
                result = self._result(
                    product_id,
                    loc,
                    status="invalid_format" if error == "invalid product ID" else (
                        "error" if error else "unresolved_product"
                    ),
                    error_message=error,
                )
                matrix.setdefault(product_id, {})[loc["name"]] = result
                if on_result:
                    on_result(result)
                continue

            async def fetch(pid=product_id, location=loc, product_mapping=mapping):
                return pid, location, product_mapping, await self.fetch_product(pid, location, product_mapping)

            tasks.append(asyncio.create_task(fetch()))

        def emit(result: dict) -> None:
            matrix.setdefault(result["product_id"], {})[result["city"]] = result
            if on_result:
                on_result(result)

        failed = []
        for task in asyncio.as_completed(tasks):
            pid, loc, mapping, result = await task
            if result["status"] == "error":
                failed.append((pid, loc, mapping))
            else:
                emit(result)

        if failed:
            logger.info("[Instamart API] retrying %d failed pairs on a fresh cookie", len(failed))
            await self._refresh_cookies(self._cookie_generation)
            for result in await asyncio.gather(
                *(self.fetch_product(pid, loc, mapping) for pid, loc, mapping in failed)
            ):
                emit(result)

        return matrix

    async def scrape_one(self, product_id: str, loc: dict) -> dict:
        matrix = await self.scrape_pairs([(product_id, loc)])
        normalized = product_id.strip().upper()
        return matrix[normalized][loc["name"]]
