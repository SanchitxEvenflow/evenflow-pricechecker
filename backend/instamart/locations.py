"""
locations.py
Single source of truth for all geographic coordinates and pincodes required for scraping.
"""

LOCATIONS = [
    {"name": "Bangalore", "lat": 12.912604, "lng": 77.652616, "pincode": "560102", "store_id": "1231052", "layoutId": ""},
    {"name": "NCR", "lat": 28.417938, "lng": 77.056187, "pincode": "122018", "store_id": "1389633", "layoutId": ""},
    {"name": "Mumbai", "lat": 19.193312, "lng": 72.839187, "pincode": "400064", "store_id": "1239162", "layoutId": ""},
    {"name": "Hyderabad", "lat": 17.435313, "lng": 78.340688, "pincode": "500111", "store_id": "1387565", "layoutId": ""},
    {"name": "Kolkata", "lat": 22.507562, "lng": 88.380813, "pincode": "700078", "store_id": "1403460", "layoutId": ""},
    {"name": "Pune", "lat": 18.570437, "lng": 73.908812, "pincode": "411014", "store_id": "1389691", "layoutId": ""},
    {"name": "Ahmedabad", "lat": 23.146687, "lng": 72.550562, "pincode": "382421", "store_id": "1388195", "layoutId": ""},
    {"name": "Chennai", "lat": 12.857688, "lng": 80.232062, "pincode": "600119", "store_id": "1391892", "layoutId": ""},
]

# Dict keyed by city name for fast lookup
LOCATIONS_BY_CITY = {loc["name"]: loc for loc in LOCATIONS}

CITY_NAMES = [loc["name"] for loc in LOCATIONS]

