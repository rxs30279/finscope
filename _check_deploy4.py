"""Check the deployed frontend - find the min score select element."""

import urllib.request, ssl

ctx = ssl.create_default_context()

url = "https://finscope-roan.vercel.app/static/js/main.f19d38b2.js"
r = urllib.request.urlopen(url, context=ctx, timeout=30)
js = r.read().decode()

# Find "Min score" label
idx = js.find("Min score")
if idx >= 0:
    print(f"Found 'Min score' at position {idx}")
    start = max(0, idx - 300)
    end = min(len(js), idx + 500)
    print(f"Context:\n{js[start:end]}")
    print()

# Find the select element options for min score
# Look for "0 (all)"
idx = js.find("0 (all)")
if idx >= 0:
    print(f"Found '0 (all)' at position {idx}")
    start = max(0, idx - 200)
    end = min(len(js), idx + 300)
    print(f"Context:\n{js[start:end]}")
    print()

# Find the onChange handler for the min score select
# Look for the pattern around the select value
idx = js.find("Min score")
if idx >= 0:
    # Find the select element after "Min score"
    select_start = js.find("<select", idx)
    if select_start >= 0:
        select_end = js.find("</select>", select_start)
        if select_end >= 0:
            print(f"Select element for Min score:")
            print(js[select_start : select_end + 9])
