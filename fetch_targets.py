#!/usr/bin/env python3
"""
MarketHrive — Download fresh targets.csv from public repo.

This script downloads the LATEST targets.csv generated from production DB.
Run this every time you want to scrape — it always gets fresh data.

Usage:
    python fetch_targets.py
    python fetch_targets.py --output my_targets.csv
"""
import os, sys, urllib.request

TARGETS_URL = "https://raw.githubusercontent.com/lutfornaharlata/markethrive-toolkit/main/targets.csv?t=" + str(__import__('time').time())

def main():
    output = 'targets.csv'
    if len(sys.argv) > 1 and sys.argv[1] == '--output' and len(sys.argv) > 2:
        output = sys.argv[2]

    print(f"=== Downloading fresh targets.csv ===")
    print(f"Source: {TARGETS_URL[:80]}...")
    try:
        # Add cache-busting timestamp
        import time
        url = f"https://raw.githubusercontent.com/lutfornaharlata/markethrive-toolkit/main/targets.csv?t={int(time.time())}"
        req = urllib.request.Request(url, headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req) as response:
            data = response.read()
        with open(output, 'wb') as f:
            f.write(data)
        size = os.path.getsize(output)
        with open(output, encoding='utf-8') as f:
            lines = sum(1 for _ in f) - 1
        print(f"\n✅ Saved to {output}")
        print(f"   Size: {size:,} bytes")
        print(f"   Businesses: {lines}")
        print(f"\nNext: python scrape.py")
    except Exception as e:
        print(f"\n❌ Download failed: {e}")
        print(f"\nAlternative: open this URL in browser:")
        print(f"  https://raw.githubusercontent.com/lutfornaharlata/markethrive-toolkit/main/targets.csv")
        print(f"  Save As → targets.csv")
        sys.exit(1)

if __name__ == '__main__':
    main()
