"""Check the deployed frontend - find the filtered useMemo logic."""

import urllib.request, ssl

ctx = ssl.create_default_context()

url = "https://finscope-roan.vercel.app/static/js/main.f19d38b2.js"
r = urllib.request.urlopen(url, context=ctx, timeout=30)
js = r.read().decode()

# Find the filtered useMemo - look for the pattern around the sort logic
# From the previous output, the sort logic is at position 626715
# Let me look at the broader context

# Find the useMemo that contains the filter logic
# Look for the pattern: return"llm"===L
idx = js.find('return"llm"===L')
if idx >= 0:
    print(f"Found sort logic at position {idx}")
    # Go back to find the start of the useMemo
    start = max(0, idx - 500)
    end = min(len(js), idx + 500)
    print(f"Context:\n{js[start:end]}")
    print()

# Also look for the tier filter logic
# Look for .filter after the sort logic
idx2 = js.find('"A"===e.tier')
if idx2 >= 0:
    print(f"Found 'A'===e.tier at position {idx2}")
    start = max(0, idx2 - 300)
    end = min(len(js), idx2 + 200)
    print(f"Context:\n{js[start:end]}")
