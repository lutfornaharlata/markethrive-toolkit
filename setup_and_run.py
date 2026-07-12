#!/usr/bin/env python3
"""All-in-one bootstrap: install deps + download files + run scraper."""
import os, sys, subprocess, urllib.request

REPO = "https://raw.githubusercontent.com/lutfornaharlata/markethrive-toolkit/main"
FILES = ["scrape.py", "targets.csv"]

def download(url, dest):
    print(f"  Downloading {dest}...", flush=True)
    try:
        urllib.request.urlretrieve(url, dest)
        print(f"  ✅ {dest} ({os.path.getsize(dest):,} bytes)", flush=True)
        return True
    except Exception as e:
        print(f"  ❌ {e}", flush=True)
        return False

def main():
    print("=" * 60)
    print("  MarketHrive Scraper Setup", flush=True)
    print("=" * 60)

    # Check deps
    print("\n[1/3] Checking dependencies...", flush=True)
    for pkg, pip_name in [("requests", "requests"), ("bs4", "beautifulsoup4")]:
        try:
            __import__(pkg)
            print(f"  ✅ {pip_name}", flush=True)
        except ImportError:
            print(f"  Installing {pip_name}...", flush=True)
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", pip_name])

    # Download files
    print("\n[2/3] Downloading files...", flush=True)
    for f in FILES:
        if not download(f"{REPO}/{f}", f):
            sys.exit(1)

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
