#!/usr/bin/env python3
import requests

API_KEY = "37|O9MtqGOSCJ6b6FNEmCW7cxmjh3B7HsIxLMr15G9I"
headers = {"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}

for endpoint in ["/api/stock", "/api/contacts", "/stock", "/api/v1/stock"]:
    url = f"https://miizy.com/miizy{endpoint}"
    try:
        r = requests.get(url, headers=headers, params={"ville":"Lyon","typologie":"T2"}, timeout=10)
        print(f"{endpoint}: {r.status_code}")
        if r.status_code == 200:
            print(f"  -> {r.text[:300]}")
    except Exception as e:
        print(f"{endpoint}: ERROR - {e}")
