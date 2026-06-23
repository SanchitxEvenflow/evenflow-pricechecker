"""Flipkart Minutes location catalog (Sample configuration)."""

LOCATIONS = [
    {"name": "Bangalore", "area": "HSR", "lat": 12.911862, "lng": 77.644592, "pincode": "560102"},

]

LOCATIONS_BY_CITY = {loc["name"]: loc for loc in LOCATIONS}
CITY_NAMES = [loc["name"] for loc in LOCATIONS]
