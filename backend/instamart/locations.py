"""
locations.py
Geographic coordinates for Instamart scraping — one entry per sheet city.

`name` MUST match utils.scrape_helpers.INSTAMART_CITIES (the sheet column order),
so scraped results map 1:1 onto sheet columns with no waste and no collisions.

lat/lng are city-area coordinates. The browser scraper spoofs these as GPS and
clicks Swiggy's "Use current location", which reverse-geocodes to the nearest
serviceable Instamart store — so an approximate area coord is enough.
"""

LOCATIONS = [
    {"name": "Bangalore", "area": "HSR",          "lat": 12.912604,  "lng": 77.652616},
    {"name": "NCR",       "area": "Gurgaon DLF",  "lat": 28.4641637, "lng": 77.0823482},
    {"name": "Mumbai",    "area": "Andheri",      "lat": 19.113610,  "lng": 72.869700},
    {"name": "Hyderabad", "area": "Gachibowli",   "lat": 17.4358411, "lng": 78.3467857},
    {"name": "Kolkata",   "area": "Salt Lake",    "lat": 22.580000,  "lng": 88.420000},
    {"name": "Pune",      "area": "Koregaon Park","lat": 18.536200,  "lng": 73.893900},
    {"name": "Ahmedabad", "area": "Adalaj",       "lat": 23.146687,  "lng": 72.550562},
    {"name": "Chennai",   "area": "Anna Nagar",   "lat": 13.084873,  "lng": 80.210175},
]

# Dict keyed by city name for fast lookup
LOCATIONS_BY_CITY = {loc["name"]: loc for loc in LOCATIONS}

CITY_NAMES = [loc["name"] for loc in LOCATIONS]
