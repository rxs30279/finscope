"""Test the production RNS API endpoint."""

import urllib.request, json, ssl

ctx = ssl.create_default_context()

# Test with min_score=0
url = "https://finscope.vercel.app/api/rns/latest?min_score=0&hours=72&limit=500"
try:
    r = urllib.request.urlopen(url, context=ctx, timeout=30)
    data = json.loads(r.read())
    tiers = {}
    for x in data:
        tiers[x["tier"]] = tiers.get(x["tier"], 0) + 1
    print(f"min_score=0: Total={len(data)}, By tier={tiers}")
except Exception as e:
    print(f"min_score=0 FAILED: {e}")

# Test with min_score=20 (default)
url2 = "https://finscope.vercel.app/api/rns/latest?min_score=20&hours=72&limit=500"
try:
    r = urllib.request.urlopen(url2, context=ctx, timeout=30)
    data = json.loads(r.read())
    tiers = {}
    for x in data:
        tiers[x["tier"]] = tiers.get(x["tier"], 0) + 1
    print(f"min_score=20: Total={len(data)}, By tier={tiers}")
except Exception as e:
    print(f"min_score=20 FAILED: {e}")
