#!/usr/bin/env python3
"""
MarketHrive — Download latest targets.csv from public repo.

This version does NOT require psycopg2 or any database connection.
Just downloads the pre-generated targets.csv from GitHub.
"""
import os, sys, urllib.request

TARGETS_URL = "https://raw.githubusercontent.com/lutfornaharlata/markethrive-toolkit/main/targets.csv"
OUTPUT = "targets.csv"

def main():
    print("=== MarketHrive — Downloading targets.csv ===")
    print(f"Source: {TARGETS_URL}")
    try:
        urllib.request.urlretrieve(TARGETS_URL, OUTPUT)
        size = os.path.getsize(OUTPUT)
        with open(OUTPUT, encoding='utf-8') as f:
            lines = sum(1 for _ in f) - 1  # exclude header
        print(f"\n✅ Saved to {OUTPUT}")
        print(f"   Size: {size:,} bytes")
        print(f"   Businesses: {lines}")
        print(f"\nNext: python scrape.py")
    except Exception as e:
        print(f"\n❌ Download failed: {e}")
        print(f"\nAlternative: open this URL in browser and save as targets.csv:")
        print(f"  {TARGETS_URL}")
        sys.exit(1)

if __name__ == '__main__':
    main()
