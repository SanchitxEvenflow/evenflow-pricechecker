"""
locations.py
Single source of truth for all geographic coordinates and pincodes required for scraping.
"""

LOCATIONS = [
    {"name": "Bangalore", "lat": 12.912604, "lng": 77.652616, "pincode": "560102"},
    {"name": "NCR", "lat": 28.417938, "lng": 77.056187, "pincode": "122018"},
    {"name": "Mumbai", "lat": 19.193312, "lng": 72.839187, "pincode": "400064"},
    {"name": "Hyderabad", "lat": 17.435313, "lng": 78.340688, "pincode": "500111"},
    {"name": "Kolkata", "lat": 22.507562, "lng": 88.380813, "pincode": "700078"},
    {"name": "Pune", "lat": 18.570437, "lng": 73.908812, "pincode": "411014"},
    {"name": "Ahmedabad", "lat": 23.146687, "lng": 72.550562, "pincode": "382421"},
    {"name": "Chennai", "lat": 12.857688, "lng": 80.232062, "pincode": "600119"},
    {"name": "Patna", "lat": 25.621063, "lng": 85.073688, "pincode": "800001"},
    {"name": "Dehradun", "lat": 30.370688, "lng": 77.970187, "pincode": "248007"},
]

# Dict keyed by city name for fast lookup
LOCATIONS_BY_CITY = {loc["name"]: loc for loc in LOCATIONS}

CITY_NAMES = [loc["name"] for loc in LOCATIONS]
