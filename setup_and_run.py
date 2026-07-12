#!/usr/bin/env python3
"""All-in-one bootstrap: install deps + download fresh files + run scraper."""
import os, sys, subprocess, urllib.request, json, base64, time

REPO = "lutfornaharlata/markethrive-toolkit"

def github_download(filename, dest):
    """Download file via GitHub API (bypasses CDN cache)."""
    print(f"  Downloading {filename}...", flush=True)
    try:
        url = f"https://api.github.com/repos/{REPO}/contents/{filename}?t={int(time.time())}"
        req = urllib.request.Request(url, headers={
            'Accept': 'application/vnd.github.v3+json',
            'Cache-Control': 'no-cache',
            'User-Agent': 'markethrive-scraper',
        })
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
        content = base64.b64decode(data['content'])
        with open(dest, 'wb') as f:
            f.write(content)
        print(f"  ✅ {dest} ({os.path.getsize(dest):,} bytes)", flush=True)
        return True
    except Exception as e:
        print(f"  ❌ {e}", flush=True)
        return False

def main():
    print("=" * 60, flush=True)
    print("  MarketHrive Scraper Setup (Fresh Data)", flush=True)
    print("=" * 60, flush=True)

    # Check deps
    print("\n[1/3] Checking dependencies...", flush=True)
    for pkg, pip_name in [("requests", "requests"), ("bs4", "beautifulsoup4")]:
        try:
            __import__(pkg)
            print(f"  ✅ {pip_name}", flush=True)
        except ImportError:
            print(f"  Installing {pip_name}...", flush=True)
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", pip_name])

    # Download fresh files via GitHub API
    print("\n[2/3] Downloading fresh files (GitHub API)...", flush=True)
    if not github_download("scrape.py", "scrape.py"):
        sys.exit(1)
    if not github_download("targets.csv", "targets.csv"):
        sys.exit(1)

    # Show stats
    print(f"\n  📊 targets.csv summary:", flush=True)
    import csv
    with open("targets.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    print(f"     Total businesses: {len(rows)}", flush=True)
    from collections import Counter
    cities = Counter(f"{r['city']}, {r['state_code']}" for r in rows)
    for city, count in cities.most_common():
        print(f"     {city}: {count}", flush=True)

    # Run scraper
    print("\n[3/3] Starting scraper...", flush=True)
    print("-" * 60, flush=True)
    import importlib.util
    spec = importlib.util.spec_from_file_location("scrape", "scrape.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.argv = ["scrape.py"]
    mod.main()

if __name__ == "__main__":
    main()
