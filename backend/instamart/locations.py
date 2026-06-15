"""
locations.py
Single source of truth for all geographic coordinates and pincodes required for scraping.
"""

LOCATIONS = [
    {"name": "Bangalore", "area": "HSR", "lat": 12.912604, "lng": 77.652616, "pincode": "560102", "store_id": "1231052"},
    {"name": "Gurgaon", "area": "DLF 4", "lat": 28.4641637, "lng": 77.0823482, "pincode": "122009", "store_id": "1239163"},
    {"name": "Chennai", "area": "Anna Nagar", "lat": 13.084873, "lng": 80.210175, "pincode": "600040", "store_id": "1403023"},
    {"name": "Patna", "area": "Phulwari", "lat": 25.621063, "lng": 85.073688, "pincode": "800001", "store_id": "1403365"},
    {"name": "Lucknow", "area": "Gomti Nagar", "lat": 26.8524588, "lng": 81.0202533, "pincode": "226010", "store_id": "1404095"},
    {"name": "Kochi", "area": "Kumbalangi", "lat": 9.8803553, "lng": 76.2768755, "pincode": "682007", "store_id": "1402451"},
    {"name": "Bangalore", "area": "Koramangala", "lat": 12.9261382, "lng": 77.6221091, "pincode": "560034", "store_id": "1404944"},
    {"name": "Ahmedabad", "area": "Adalaj", "lat": 23.146687, "lng": 72.550562, "pincode": "382421", "store_id": "1388195"},
    {"name": "Hyderabad", "area": "Serilingampalle", "lat": 17.4358411, "lng": 78.3467857, "pincode": "500032", "store_id": "1387565"},
]

# Dict keyed by city name for fast lookup
LOCATIONS_BY_CITY = {loc["name"]: loc for loc in LOCATIONS}

CITY_NAMES = [loc["name"] for loc in LOCATIONS]

