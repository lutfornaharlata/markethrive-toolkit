#!/usr/bin/env python3
"""
MarketHrive — Download fresh targets.csv from GitHub API.

Uses GitHub API (not raw.githubusercontent) to bypass CDN cache.
Always gets the latest version of targets.csv.

Usage:
    python fetch_targets.py
    python fetch_targets.py --output my_targets.csv
"""
import os, sys, json, urllib.request, time

# GitHub API endpoint — always returns fresh data
API_URL = "https://api.github.com/repos/lutfornaharlata/markethrive-toolkit/contents/targets.csv"

def main():
    output = 'targets.csv'
    if '--output' in sys.argv:
        idx = sys.argv.index('--output')
        if idx + 1 < len(sys.argv):
            output = sys.argv[idx + 1]

    print(f"=== Downloading fresh targets.csv ===")
    print(f"Source: GitHub API (bypasses CDN cache)")
    try:
        # Add cache-busting timestamp
        url = f"{API_URL}?t={int(time.time())}"
        req = urllib.request.Request(url, headers={
            'Accept': 'application/vnd.github.v3+json',
            'Cache-Control': 'no-cache',
            'User-Agent': 'markethrive-scraper',
        })
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())

        # API returns base64-encoded content
        import base64
        content = base64.b64decode(data['content'])

        with open(output, 'wb') as f:
            f.write(content)

        size = os.path.getsize(output)
        with open(output, encoding='utf-8') as f:
            lines = sum(1 for _ in f) - 1

        print(f"\n✅ Saved to {output}")
        print(f"   Size: {size:,} bytes")
        print(f"   Businesses: {lines}")

        # Show breakdown by city
        from collections import Counter
        cities = Counter()
        with open(output, encoding='utf-8') as f:
            import csv
            reader = csv.DictReader(f)
            for row in reader:
                cities[f"{row['city']}, {row['state_code']}"] += 1
        print(f"\nBy city:")
        for city, count in cities.most_common():
            print(f"  {city}: {count}")

        print(f"\nNext: python scrape.py")

    except Exception as e:
        print(f"\n❌ Download failed: {e}")
        print(f"\nAlternative: open this URL in browser:")
        print(f"  https://github.com/lutfornaharlata/markethrive-toolkit/raw/main/targets.csv")
        print(f"  Save As → targets.csv")
        sys.exit(1)

if __name__ == '__main__':
    main()
