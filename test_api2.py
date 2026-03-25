#!/usr/bin/env python3
import requests

API_KEY = "37|O9MtqGOSCJ6b6FNEmCW7cxmjh3B7HsIxLMr15G9I"
headers = {"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}

params_list = [
    {"ville": "Lyon", "typologie": "T2"},
    {"ville": "lyon", "typologie": "t2"},
    {"ville": "Paris", "typologie": "T2"},
    {"typologie": "T2"},
    {"ville": "Lyon"},
    {}
]

for params in params_list:
    try:
        r = requests.get("https://miizy.com/miizy/stock", headers=headers, params=params, timeout=10)
        data = r.json()
        total = data.get("original", {}).get("total_estates", 0)
        print(f"Params {params}: {total} biens trouvés")
    except Exception as e:
        print(f"Params {params}: ERREUR - {e}")
