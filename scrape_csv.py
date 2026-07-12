#!/usr/bin/env python3
"""
MarketHrive — Scrape a Google Sheet CSV and add logo_url + email columns.

Input: CSV downloaded from Google Sheets (with Name, Website, Address, etc. columns)
Output: Same CSV with 2 new columns filled in (logo_url, email)

This script:
1. Reads input CSV
2. For each row, scrapes the website for logo + email
3. Writes output CSV with logo_url + email columns added/filled

Usage:
    python scrape_csv.py --input huntsville.csv
    python scrape_csv.py --input huntsville.csv --output huntsville_scraped.csv
    python scrape_csv.py --input huntsville.csv --threads 12
"""
import argparse, csv, os, re, sys, time, threading, random
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0',
]

EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
REJECT_DOMAINS = {'wixpress.com','wix.com','sentry.io','example.com','example.org',
                  'sample.org','yourdomain.com','domain.com','email.com','mail.com',
                  'jpg','png','gif','svg','webp'}
REJECT_LOCAL = {'example','test','sample','sentry','wix','noreply','no-reply',
                'donotreply','sharklasers','mailinator','guerrillamail','yopmail',
                'your','you','name','user','email','e'}
CONTACT_PATHS = ['/contact-us/','/contact/','/contact','/contact_us/',
                 '/about-us/','/about/','/about','/reach-us/','/connect/']

lock = threading.Lock()
stats = {'scraped': 0, 'logos_found': 0, 'emails_found': 0, 'failed': 0, 'total': 0}

# ─── Same helpers as scrape.py ────────────────────────────────
def fetch(url, timeout=10, retries=2):
    for attempt in range(retries):
        headers = {**HEADERS, 'User-Agent': random.choice(USER_AGENTS)}
        try:
            r = requests.get(url, headers=headers, timeout=timeout,
                              allow_redirects=True, verify=True)
            if r.status_code == 200:
                ct = r.headers.get('Content-Type', '')
                if 'html' in ct or 'text' in ct or ct == '':
                    return r
            elif r.status_code in (403, 429):
                continue
            else:
                return None
        except: continue
    return None

def extract_logo_url(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    for link in soup.find_all('link', rel=True):
        rel = (link.get('rel') or [])
        if any(r.lower() in ('icon', 'shortcut icon', 'apple-touch-icon',
                              'apple-touch-icon-precomposed') for r in rel):
            href = link.get('href')
            if href and not href.startswith('data:'):
                try: return urljoin(base_url, href)
                except: pass
    meta = soup.find('meta', property='og:image')
    if meta and meta.get('content'):
        try: return urljoin(base_url, meta['content'])
        except: pass
    for img in soup.find_all('img'):
        cls = ' '.join(img.get('class') or [])
        iid = img.get('id') or ''
        alt = (img.get('alt') or '').lower()
        src = img.get('src') or ''
        combined = (cls + ' ' + iid + ' ' + alt).lower()
        if any(x in combined for x in ['logo', 'brand']) and src:
            if not src.startswith('data:'):
                try: return urljoin(base_url, src)
                except: pass
    header = soup.find('header')
    if header:
        img = header.find('img')
        if img and img.get('src') and not img['src'].startswith('data:'):
            try: return urljoin(base_url, img['src'])
            except: pass
    return None

def is_valid_email(email):
    e = (email or '').lower().strip().rstrip('.,;:)}\'"').split('?')[0].split('&')[0]
    if not e or '@' not in e or '.' not in e: return False
    if len(e) > 80 or len(e) < 6: return False
    if e.startswith(('http://','https://')): return False
    local, _, domain = e.partition('@')
    if not local or not domain: return False
    if not re.match(r'^[a-z0-9._%+-]+$', local): return False
    if e.startswith(('example@','test@','sample@','your@','you@','name@',
                      'email@','e@','user@')): return False
    if domain in REJECT_DOMAINS: return False
    if local in REJECT_LOCAL: return False
    if 'sentry' in e or 'example' in e or 'wix' in e: return False
    if re.match(r'^\+?\d{3,}', local): return False
    if domain.endswith(('.jpg','.png','.gif','.svg','.webp')): return False
    return True

def extract_emails(html):
    seen = set(); emails = []
    for m in EMAIL_RE.findall(html):
        if m not in seen:
            seen.add(m); emails.append(m)
    for m in re.findall(r'mailto:([^"?>\s]+)', html, re.IGNORECASE):
        e = m.strip().rstrip('.,;:)}\'"')
        if e and e not in seen:
            seen.add(e); emails.append(e)
    return emails

def is_url(s):
    return bool(s) and bool(re.match(r'^https?://', s.strip(), re.IGNORECASE))

# ─── Worker ───────────────────────────────────────────────────
def worker(row, name_col, website_col):
    name = row.get(name_col, '') or ''
    website = row.get(website_col, '') or ''
    with lock:
        stats['scraped'] += 1
        n = stats['scraped']

    logo_url = ''
    email = ''

    if website and is_url(website):
        try:
            resp = fetch(website, timeout=10)
            if resp:
                logo_url = extract_logo_url(resp.text, resp.url) or ''
                emails = extract_emails(resp.text)
                email = next((e.lower() for e in emails if is_valid_email(e)), '')
                # Try contact pages if no email
                if not email:
                    parsed = urlparse(resp.url)
                    base = f"{parsed.scheme}://{parsed.netloc}"
                    for path in CONTACT_PATHS:
                        page = fetch(urljoin(base, path), timeout=8)
                        if page:
                            emails = extract_emails(page.text)
                            email = next((e.lower() for e in emails if is_valid_email(e)), '')
                            if email: break
            else:
                with lock: stats['failed'] += 1
        except:
            with lock: stats['failed'] += 1
    else:
        with lock: stats['failed'] += 1

    if logo_url:
        with lock: stats['logos_found'] += 1
    if email:
        with lock: stats['emails_found'] += 1

    if n % 20 == 0:
        elapsed = time.time() - worker.start
        rate = n / max(elapsed, 1)
        eta = (stats['total'] - n) / max(rate, 0.1)
        print(f"  [{n}/{stats['total']}] logos={stats['logos_found']} "
              f"emails={stats['emails_found']} failed={stats['failed']} "
              f"| {elapsed:.0f}s, ETA {eta:.0f}s", flush=True)

    return {'row_idx': row.get('_idx', 0), 'logo_url': logo_url, 'email': email}

worker.start = time.time()

# ─── Main ─────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description='Scrape Google Sheet CSV for logos + emails')
    ap.add_argument('--input', required=True, help='Input CSV path (from Google Sheets)')
    ap.add_argument('--output', default='', help='Output CSV path (default: input_scraped.csv)')
    ap.add_argument('--threads', type=int, default=8)
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ Input file not found: {args.input}")
        sys.exit(1)

    output = args.output or args.input.replace('.csv', '_scraped.csv')

    print("=" * 60)
    print("  MarketHrive CSV Scraper")
    print("=" * 60)
    print(f"  Input:  {args.input}")
    print(f"  Output: {output}")
    print(f"  Threads: {args.threads}")

    # Read input CSV
    with open(args.input, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        input_rows = list(reader)
        fieldnames = reader.fieldnames or []

    print(f"\n  Loaded {len(input_rows)} rows")
    print(f"  Columns: {fieldnames}")

    # Find Name + Website columns (case-insensitive, partial match)
    name_col = None
    website_col = None
    for fn in fieldnames:
        fn_lower = fn.lower().strip()
        if not name_col and 'name' in fn_lower:
            name_col = fn
        if not website_col and ('website' in fn_lower or 'url' == fn_lower):
            website_col = fn

    if not name_col:
        print(f"\n❌ Could not find a 'Name' column. Found: {fieldnames}")
        sys.exit(1)
    if not website_col:
        print(f"\n❌ Could not find a 'Website' column. Found: {fieldnames}")
        sys.exit(1)

    print(f"\n  Name column:    '{name_col}'")
    print(f"  Website column: '{website_col}'")

    # Ensure logo_url + email columns exist in output
    output_fields = list(fieldnames)
    if 'logo_url' not in [f.lower() for f in output_fields]:
        output_fields.append('logo_url')
    if 'email' not in [f.lower() for f in output_fields]:
        output_fields.append('email')

    # Find actual column names (case-insensitive)
    logo_field = next((f for f in output_fields if f.lower() == 'logo_url'), 'logo_url')
    email_field = next((f for f in output_fields if f.lower() == 'email'), 'email')

    # Add _idx for tracking
    for i, row in enumerate(input_rows):
        row['_idx'] = i

    stats['total'] = len(input_rows)
    print(f"\n  Starting scrape... (ETA: ~{len(input_rows) * 2 // 60} min)")
    print("-" * 60)

    # Scrape in parallel
    worker.start = time.time()
    results = {}
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futures = [ex.submit(worker, row, name_col, website_col) for row in input_rows]
        for f in as_completed(futures):
            try:
                r = f.result()
                results[r['row_idx']] = r
            except Exception as e:
                print(f"  [ERROR]: {str(e)[:80]}", flush=True)

    # Write output CSV
    print(f"\n{'='*60}")
    print(f"  Writing output: {output}")
    with open(output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        for i, row in enumerate(input_rows):
            row.pop('_idx', None)
            r = results.get(i, {})
            # Only fill if not already present
            if not row.get(logo_field):
                row[logo_field] = r.get('logo_url', '')
            if not row.get(email_field):
                row[email_field] = r.get('email', '')
            writer.writerow(row)

    elapsed = time.time() - worker.start
    print(f"\n✅ Done in {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  Total scraped:   {stats['scraped']}")
    print(f"  Logos found:     {stats['logos_found']}")
    print(f"  Emails found:    {stats['emails_found']}")
    print(f"  Failed:          {stats['failed']}")
    print(f"\n📤 Upload {output} to /admin/upload-data")
    print(f"   Mode: 'Sheet + Logo/Email'")

if __name__ == '__main__':
    main()
