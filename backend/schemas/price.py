"""Pydantic v2 request/response models for price checking endpoints."""

import re
from datetime import datetime
from pydantic import BaseModel, field_validator


# ── Request Models ──────────────────────────────────────────────────────────

class AmazonRequest(BaseModel):
    asin: str
    force_refresh: bool = False

    @field_validator("asin")
    @classmethod
    def validate_asin(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^[A-Z0-9]{10}$", v):
            raise ValueError("ASIN must be exactly 10 alphanumeric characters")
        return v


class FlipkartRequest(BaseModel):
    fsn: str
    force_refresh: bool = False

    @field_validator("fsn")
    @classmethod
    def validate_fsn(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^[A-Z0-9]{16}$", v):
            raise ValueError("FSN must be exactly 16 alphanumeric characters")
        return v


class BothRequest(BaseModel):
    asin: str
    fsn: str
    force_refresh: bool = False

    @field_validator("asin")
    @classmethod
    def validate_asin(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^[A-Z0-9]{10}$", v):
            raise ValueError("ASIN must be exactly 10 alphanumeric characters")
        return v

    @field_validator("fsn")
    @classmethod
    def validate_fsn(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^[A-Z0-9]{16}$", v):
            raise ValueError("FSN must be exactly 16 alphanumeric characters")
        return v


# ── Response Models ─────────────────────────────────────────────────────────

class AmazonResponse(BaseModel):
    asin: str
    price: str
    mrp: str | None = None
    rating: str | None = None
    rating_count: str | None = None
    rating_breakdown: dict[str, str | None] | None = None
    rank_raw: str | None = None
    rank_value: str | None = None
    rank_category: str | None = None
    sub_rank_value: str | None = None
    sub_rank_category: str | None = None
    parent_node: str | None = None
    child_node: str | None = None
    category_path: str | None = None
    status: str
    platform: str = "amazon"
    url: str
    checked_at: datetime


class FlipkartResponse(BaseModel):
    fsn: str
    price: str
    rating: str | None = None
    rating_count: str | None = None
    fulfilled_by: str | None = None
    status: str
    platform: str = "flipkart"
    url: str
    resolved_url: str | None = None
    checked_at: datetime


class BothResponse(BaseModel):
    asin: str
    fsn: str
    amazon: AmazonResponse
    flipkart: FlipkartResponse
    price_diff: str | None = None
    cheaper_on: str | None = None


class HealthResponse(BaseModel):
    status: str
    proxy_pool_size: int
    playwright_ready: bool
    timestamp: datetime


# ── Blinkit Models ──────────────────────────────────────────────────────────

class BlinkitRequest(BaseModel):
    product_id: str
    city: str


class BlinkitAllCitiesRequest(BaseModel):
    product_ids: list[str]


class BlinkitCityResult(BaseModel):
    product_id: str
    city: str
    title: str | None = None
    price: float | None = None
    mrp: float | None = None
    status: str
    is_sold_out: bool = False
    url: str
    checked_at: str


class BlinkitResponse(BlinkitCityResult):
    pass


# ── Zepto Models ────────────────────────────────────────────────────────────

class ZeptoRequest(BaseModel):
    product_id: str
    city: str


class ZeptoAllCitiesRequest(BaseModel):
    product_ids: list[str]


class ZeptoCityResult(BaseModel):
    product_id: str
    city: str
    title: str | None = None
    price: float | None = None
    mrp: float | None = None
    status: str
    is_sold_out: bool = False
    url: str
    checked_at: str
    error_message: str | None = None


class ZeptoResponse(ZeptoCityResult):
    pass


# ── Instamart Models ──────────────────────────────────────────────────────

class InstamartRequest(BaseModel):
    product_id: str
    city: str
    # address is required by the scraper contract
    address: str


class InstamartAllCitiesRequest(BaseModel):
    product_ids: list[str]


class InstamartCityResult(BaseModel):
    product_id: str
    city: str
    title: str | None = None
    price: float | None = None
    mrp: float | None = None
    status: str
    is_sold_out: bool = False
    url: str
    checked_at: str
    error_message: str | None = None


class InstamartResponse(InstamartCityResult):
    pass

