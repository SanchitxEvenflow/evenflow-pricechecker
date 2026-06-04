"""
locations.py
Single source of truth for all geographic coordinates and pincodes required for scraping.
"""

LOCATIONS = [
    {"name": "Bangalore", "lat": 12.912604, "lng": 77.652616, "pincode": "560102", "store_id": "7e5a1821-59ed-4d8a-8431-a3705afb22d2"},
    {"name": "NCR", "lat": 28.417938, "lng": 77.056187, "pincode": "122018", "store_id": "96348a97-316b-4e61-963d-05f9827366de"},
    {"name": "Mumbai", "lat": 19.193312, "lng": 72.839187, "pincode": "400064", "store_id": "d390ee2b-1c8f-4236-9c8b-b60173fd330a"},
    {"name": "Hyderabad", "lat": 17.435313, "lng": 78.340688, "pincode": "500111", "store_id": "da5149e0-007e-4134-bc25-497d6ea3c5b2"},
    {"name": "Kolkata", "lat": 22.507562, "lng": 88.380813, "pincode": "700078", "store_id": "547ab61d-8d0e-47b5-a5b4-82952f43e814"},
    {"name": "Pune", "lat": 18.570437, "lng": 73.908812, "pincode": "411014", "store_id": "315e9d84-2c4a-45b2-88fb-f6733794efba"},
    {"name": "Ahmedabad", "lat": 23.146687, "lng": 72.550562, "pincode": "382421", "store_id": "594e08e1-87d1-4502-9e92-182e895a6c0c"},
    {"name": "Chennai", "lat": 12.857688, "lng": 80.232062, "pincode": "600119", "store_id": "7cc8853d-4ba2-4537-808d-95a7adfcf500"},
    {"name": "Dehradun", "lat": 30.370688, "lng": 77.970187, "pincode": "248007", "store_id": "b4dc8d65-ed2e-4142-81b6-373982b13500"},
]

# Dict keyed by city name for fast lookup
LOCATIONS_BY_CITY = {loc["name"]: loc for loc in LOCATIONS}

CITY_NAMES = [loc["name"] for loc in LOCATIONS]

