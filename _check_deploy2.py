"""Check the deployed frontend for RNS tab code - deeper analysis."""

import urllib.request, re, ssl

ctx = ssl.create_default_context()

# Get the main JS bundle
url = "https://finscope-roan.vercel.app/static/js/main.f19d38b2.js"
r = urllib.request.urlopen(url, context=ctx, timeout=30)
js = r.read().decode()

# Find the tier filter logic
# Look for "all" "A" "B" "C" pattern
idx = js.find('"all"')
if idx >= 0:
    print(f"Found 'all' at position {idx}")
    print(f"Context: {js[max(0,idx-100):idx+300]}")
    print()

# Look for "Tier C"
idx = js.find("Tier C")
if idx >= 0:
    print(f"Found 'Tier C' at position {idx}")
    print(f"Context: {js[max(0,idx-100):idx+300]}")
    print()

# Look for the filter logic - search for .filter after tier
idx = js.find(".filter")
if idx >= 0:
    print(f"Found .filter at position {idx}")
    print(f"Context: {js[max(0,idx-50):idx+200]}")
    print()

# Look for the sort logic
idx = js.find("llm_score")
if idx >= 0:
    print(f"Found llm_score at position {idx}")
    print(f"Context: {js[max(0,idx-100):idx+300]}")
    print()

# Look for the min_score default value
idx = js.find("min_score=")
if idx >= 0:
    print(f"Found min_score= at position {idx}")
    # Find the full fetch URL
    start = max(0, idx - 200)
    end = min(len(js), idx + 300)
    print(f"Context: {js[start:end]}")
    print()

# Check if there's a hardcoded score threshold
idx = js.find("score>=")
if idx >= 0:
    print(f"Found score>= at position {idx}")
    print(f"Context: {js[max(0,idx-50):idx+100]}")
elif js.find("score >=") >= 0:
    idx = js.find("score >=")
    print(f"Found score >= at position {idx}")
    print(f"Context: {js[max(0,idx-50):idx+100]}")
else:
    print("No score>= or score >= found in JS bundle")
