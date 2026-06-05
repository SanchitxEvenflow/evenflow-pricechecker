"""Instamart locations.

Single source of truth for Instamart geographic coordinates and store IDs.
"""

# Canonical city order must match Blinkit intended coverage.
# (Instamart scraper returns results in whatever order the UI expects.)

LOCATIONS = [
    # store_id values are placeholders except Chennai which must start with 1401251
    {"name": "Bangalore", "lat": 12.912604, "lng": 77.652616, "pincode": "560102", "store_id": ""},
    {"name": "NCR", "lat": 28.417938, "lng": 77.056187, "pincode": "122018", "store_id": ""},
    {"name": "Mumbai", "lat": 19.193312, "lng": 72.839187, "pincode": "400064", "store_id": ""},
    {"name": "Hyderabad", "lat": 17.435313, "lng": 78.340688, "pincode": "500111", "store_id": ""},
    {"name": "Kolkata", "lat": 22.507562, "lng": 88.380813, "pincode": "700078", "store_id": ""},
    {"name": "Pune", "lat": 18.570437, "lng": 73.908812, "pincode": "411014", "store_id": ""},
    {"name": "Ahmedabad", "lat": 23.146687, "lng": 72.550562, "pincode": "382421", "store_id": ""},
    {"name": "Chennai", "lat": 12.857688, "lng": 80.232062, "pincode": "600119", "store_id": "1401251"},
    {"name": "Patna", "lat": 25.594091, "lng": 85.137564, "pincode": "800001", "store_id": ""},
    {"name": "Dehradun", "lat": 30.370688, "lng": 77.970187, "pincode": "248007", "store_id": ""},
]

LOCATIONS_BY_CITY = {loc["name"]: loc for loc in LOCATIONS}
CITY_NAMES = [loc["name"] for loc in LOCATIONS]

