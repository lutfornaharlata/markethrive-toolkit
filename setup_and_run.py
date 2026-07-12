#!/usr/bin/env python3
"""
MarketHrive Local Scraper — All-in-one bootstrap script.

Run this single file. It will:
1. Download scrape.py + targets.csv from public repo
2. Check Python dependencies
3. Run the scraper

Usage:
    python setup_and_run.py
"""
import os, sys, subprocess, urllib.request

REPO = "https://raw.githubusercontent.com/lutfornaharlata/markethrive-toolkit/main"
FILES = ["scrape.py", "targets.csv"]

def download(url, dest):
    print(f"  Downloading {url}...")
    try:
        urllib.request.urlretrieve(url, dest)
        size = os.path.getsize(dest)
        print(f"  ✅ Saved {dest} ({size:,} bytes)")
        return True
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return False

def check_dependency(package):
    try:
        __import__(package)
        return True
    except ImportError:
        return False

def install(package):
    print(f"  Installing {package}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", package])
        return True
    except Exception as e:
        print(f"  ❌ Install failed: {e}")
        return False

def main():
    print("=" * 60)
    print("  MarketHrive Local Scraper — Setup & Run")
    print("=" * 60)
    print()

    # Step 1: Check Python version
    print("Step 1: Checking Python...")
    if sys.version_info < (3, 8):
        print(f"  ❌ Python 3.8+ required, you have {sys.version}")
        sys.exit(1)
    print(f"  ✅ Python {sys.version.split()[0]}")

    # Step 2: Check dependencies
    print("\nStep 2: Checking dependencies...")
    deps = [("requests", "requests"), ("bs4", "beautifulsoup4")]
    missing = []
    for import_name, pip_name in deps:
        if check_dependency(import_name):
            print(f"  ✅ {pip_name} installed")
        else:
            print(f"  ⚠ {pip_name} not installed")
            missing.append(pip_name)

    if missing:
        print("\nInstalling missing dependencies...")
        for pkg in missing:
            install(pkg)
        # Re-check
        for import_name, _ in deps:
            if not check_dependency(import_name):
                print(f"\n❌ Could not install {import_name}. Please install manually:")
                print(f"   pip install {' '.join(missing)}")
                sys.exit(1)

    # Step 3: Download files
    print("\nStep 3: Downloading files...")
    for f in FILES:
        url = f"{REPO}/{f}"
        dest = f
        # If exists, ask to overwrite (skip interactive — just overwrite)
        if not download(url, dest):
            print(f"\n❌ Cannot download {f}.")
            print(f"   Manual download: open browser → {url} → Save As {f}")
            sys.exit(1)

    # Step 4: Verify targets.csv
    print("\nStep 4: Verifying targets.csv...")
    if not os.path.exists("targets.csv"):
        print("  ❌ targets.csv not found")
        sys.exit(1)
    with open("targets.csv", encoding="utf-8") as f:
        lines = sum(1 for _ in f) - 1
    print(f"  ✅ {lines} businesses loaded")

    # Step 5: Run scraper
    print("\n" + "=" * 60)
    print("  Setup complete! Starting scraper...")
    print("=" * 60)
    print()
    print("The scraper will visit each business website and extract:")
    print("  - Logos (favicon, og:image, logo images)")
    print("  - Emails (mailto: links, plain text, /contact pages)")
    print()
    print("Output files:")
    print("  - logos_found.csv  (business_id, logo_url)")
    print("  - emails_found.csv (business_id, email)")
    print()
    print("Press Ctrl+C to stop. You can re-run later — it'll skip already-scraped.")
    print()
    print("-" * 60)

    # Import and run scrape.py
    import importlib.util
    spec = importlib.util.spec_from_file_location("scrape", "scrape.py")
    scrape_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scrape_mod)

    # Call main with no args
    sys.argv = ["scrape.py"]
    scrape_mod.main()

if __name__ == "__main__":
    main()
