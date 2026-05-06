"""Check the deployed frontend for RNS tab code."""

import urllib.request, re, ssl

ctx = ssl.create_default_context()

# Get the HTML
url = "https://finscope-roan.vercel.app/"
r = urllib.request.urlopen(url, context=ctx, timeout=30)
html = r.read().decode()

# Find script tags
scripts = re.findall(r'src="([^"]+\.js[^"]*)"', html)
print("Scripts found:")
for s in scripts:
    print(f"  {s}")

# Get the main JS bundle
for s in scripts:
    if "/static/js/main." in s:
        js_url = "https://finscope-roan.vercel.app" + s
        print(f"\nFetching main JS bundle: {js_url}")
        r2 = urllib.request.urlopen(js_url, context=ctx, timeout=30)
        js = r2.read().decode()

        # Check for key code patterns
        checks = [
            ("min_score", "min_score" in js),
            ("minScore", "minScore" in js),
            ("Tier C", "Tier C" in js),
            ("tierFilter", "tierFilter" in js),
            ("setMinScore", "setMinScore" in js),
            ("r.score >=", "r.score >=" in js),
        ]
        print("\nCode checks:")
        for name, found in checks:
            print(f'  {name}: {"FOUND" if found else "MISSING"}')

        # Check for the min_score query parameter in the fetch URL
        if "min_score=" in js:
            # Find the context around min_score=
            idx = js.find("min_score=")
            print(f"\nContext around min_score= (chars {idx}-{idx+200}):")
            print(js[max(0, idx - 50) : idx + 200])
        break
