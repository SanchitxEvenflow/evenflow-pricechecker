import json
import re

with open("instamart_page.html", "r", encoding="utf-8") as f:
    content = f.read()

# Find any JSON-like structures that might contain product info
matches = re.finditer(r'\{[^{}]*"price"[^{}]*\}', content)
print("Found basic price objects:", len(list(matches)))

# Try to find the exact offer price
match = re.search(r'"price"\s*:\s*(\d+)', content)
if match:
    print("Found price:", match.group(1))

# check schema.org script
schema_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', content, re.DOTALL)
if schema_match:
    print("Found schema:")
    try:
        data = json.loads(schema_match.group(1))
        print(json.dumps(data, indent=2))
    except Exception as e:
        print("Schema parse error:", e)
