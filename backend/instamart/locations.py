"""
locations.py
Geographic coordinates for Instamart scraping — one entry per sheet city.

`name` MUST match utils.scrape_helpers.INSTAMART_CITIES (the sheet column order),
so scraped results map 1:1 onto sheet columns with no waste and no collisions.

Every coordinate below was verified against Instamart's home API. Environment
variables can override a store ID if Instamart remaps a service area later.
"""

import os


def _store_id(key: str, verified: str) -> str:
    return os.getenv(f"INSTAMART_STORE_ID_{key}") or verified

LOCATIONS = [
    {"name": "Bangalore - HSR",         "area": "HSR",          "lat": 12.912604,  "lng": 77.652616, "store_id": _store_id("BANGALORE_HSR", "1231052")},
    {"name": "Gurgaon",                 "area": "DLF",          "lat": 28.4641637, "lng": 77.0823482, "store_id": _store_id("GURGAON", "1239163")},
    {"name": "Chennai",                 "area": "Anna Nagar",   "lat": 13.084873,  "lng": 80.210175, "store_id": _store_id("CHENNAI", "1403023")},
    {"name": "Patna",                   "area": "Central Patna", "lat": 25.621063,  "lng": 85.073688, "store_id": _store_id("PATNA", "1401272")},
    {"name": "Lucknow",                 "area": "Gomti Nagar",  "lat": 26.854000,  "lng": 81.010700, "store_id": _store_id("LUCKNOW", "1404095")},
    {"name": "Kochi",                   "area": "Kakkanad",     "lat": 10.015900,  "lng": 76.341900, "store_id": _store_id("KOCHI", "1404995")},
    {"name": "Bangalore - Koramangala", "area": "Koramangala", "lat": 12.935200,  "lng": 77.624500, "store_id": _store_id("BANGALORE_KORAMANGALA", "1396284")},
    {"name": "Ahmedabad",               "area": "City Centre", "lat": 23.022500,  "lng": 72.571400, "store_id": _store_id("AHMEDABAD", "1386812")},
    {"name": "Hyderabad",               "area": "Gachibowli",   "lat": 17.4358411, "lng": 78.3467857, "store_id": _store_id("HYDERABAD", "1387565")},
]

# Dict keyed by city name for fast lookup
LOCATIONS_BY_CITY = {loc["name"]: loc for loc in LOCATIONS}
# Preserve the former single-city API names while the UI uses area-specific labels.
LOCATIONS_BY_CITY["Bangalore"] = LOCATIONS[0]
LOCATIONS_BY_CITY["NCR"] = LOCATIONS[1]

CITY_NAMES = [loc["name"] for loc in LOCATIONS]
