#!/usr/bin/env python3
"""
MarketHrive — Local scraper for logos + emails.

Reads targets.csv (created by download_targets.py), visits each website,
extracts logos + emails, and saves to:
  - logos_found.csv  (business_id, logo_url)
  - emails_found.csv (business_id, email)

This script runs on YOUR machine — no Vercel timeout. Can run for hours.

Usage:
    python scrape.py
    python scrape.py --city Birmingham
    python scrape.py --niche roofing
    python scrape.py --emails-only
    python scrape.py --logos-only
    python scrape.py --threads 12
    python scrape.py --delay 3      # 3 second delay between requests
"""
import argparse, csv, os, re, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

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

# ─── Logo extraction ──────────────────────────────────────────
def extract_logo_url(html, base_url):
    """Extract logo URL using 4 strategies."""
    soup = BeautifulSoup(html, 'html.parser')

    # 1. favicon (icon, shortcut icon, apple-touch-icon)
    for link in soup.find_all('link', rel=True):
        rel = (link.get('rel') or [])
        if any(r.lower() in ('icon', 'shortcut icon', 'apple-touch-icon',
                              'apple-touch-icon-precomposed') for r in rel):
            href = link.get('href')
            if href and not href.startswith('data:'):
                try:
                    return urljoin(base_url, href)
                except: pass

    # 2. og:image
    meta = soup.find('meta', property='og:image')
    if meta and meta.get('content'):
        try: return urljoin(base_url, meta['content'])
        except: pass

    # 3. <img> with class/id/alt containing "logo" or "brand"
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

    # 4. First <img> inside <header>
    header = soup.find('header')
    if header:
        img = header.find('img')
        if img and img.get('src') and not img['src'].startswith('data:'):
            try: return urljoin(base_url, img['src'])
            except: pass

    return None

# ─── Email extraction ─────────────────────────────────────────
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
    """Extract emails from raw HTML + mailto: links."""
    seen = set(); emails = []
    for m in EMAIL_RE.findall(html):
        if m not in seen:
            seen.add(m); emails.append(m)
    for m in re.findall(r'mailto:([^"?>\s]+)', html, re.IGNORECASE):
        e = m.strip().rstrip('.,;:)}\'"')
        if e and e not in seen:
            seen.add(e); emails.append(e)
    return emails

def fetch(url, timeout=10):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout,
                          allow_redirects=True, verify=True)
        if r.status_code == 200:
            ct = r.headers.get('Content-Type', '')
            if 'html' in ct or 'text' in ct or ct == '':
                return r
    except: pass
    return None

# ─── Worker ───────────────────────────────────────────────────
def worker(biz, scrape_logos, scrape_emails, delay):
    bid = biz['business_id']
    name = biz['name']
    website = biz['website']

    with lock:
        stats['scraped'] += 1
        n = stats['scraped']

    if not website or not website.startswith('http'):
        return None

    if delay > 0:
        time.sleep(delay)

    result = {'business_id': bid, 'logo_url': None, 'email': None}

    try:
        resp = fetch(website, timeout=10)
        if not resp:
            with lock: stats['failed'] += 1
            return result

        # Logo
        if scrape_logos and not biz.get('current_logo'):
            logo_url = extract_logo_url(resp.text, resp.url)
            if logo_url:
                result['logo_url'] = logo_url
                with lock: stats['logos_found'] += 1

        # Email
        if scrape_emails and not biz.get('current_email'):
            # Try homepage first
            emails = extract_emails(resp.text)
            email = next((e.lower() for e in emails if is_valid_email(e)), None)

            # If no email, try contact pages
            if not email:
                parsed = urlparse(resp.url)
                base = f"{parsed.scheme}://{parsed.netloc}"
                for path in CONTACT_PATHS:
                    page = fetch(urljoin(base, path), timeout=8)
                    if page:
                        emails = extract_emails(page.text)
                        email = next((e.lower() for e in emails if is_valid_email(e)), None)
                        if email:
                            break

            if email:
                result['email'] = email
                with lock: stats['emails_found'] += 1
    except Exception as e:
        with lock: stats['failed'] += 1
        return None

    if n % 20 == 0:
        elapsed = time.time() - worker.start
        rate = n / max(elapsed, 1)
        eta = (stats['total'] - n) / max(rate, 0.1)
        print(f"  [{n}/{stats['total']}] logos={stats['logos_found']} "
              f"emails={stats['emails_found']} failed={stats['failed']} "
              f"| {elapsed:.0f}s elapsed, ETA {eta:.0f}s", flush=True)

    return result

worker.start = time.time()

# ─── Main ─────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--city', default='', help='Filter targets.csv by city')
    ap.add_argument('--niche', default='', help='Filter by niche slug')
    ap.add_argument('--emails-only', action='store_true', help='Skip logos')
    ap.add_argument('--logos-only', action='store_true', help='Skip emails')
    ap.add_argument('--threads', type=int, default=8)
    ap.add_argument('--delay', type=float, default=0, help='Delay between requests (seconds)')
    ap.add_argument('--targets', default='targets.csv', help='Input CSV path')
    args = ap.parse_args()

    scrape_logos = not args.emails_only
    scrape_emails = not args.logos_only

    print("=== MarketHrive Local Scraper ===")
    print(f"Threads: {args.threads} | Logos: {scrape_logos} | Emails: {scrape_emails}")

    if not os.path.exists(args.targets):
        print(f"\n❌ {args.targets} not found!")
        print(f"   Run: python download_targets.py")
        return

    # Load targets
    businesses = []
    with open(args.targets, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if args.city and args.city.lower() not in row['city'].lower():
                continue
            if args.niche and row['niche_slug'] != args.niche:
                continue
            businesses.append(row)

    stats['total'] = len(businesses)
    print(f"\nLoaded {len(businesses)} businesses from {args.targets}")

    if not businesses:
        print("No businesses match the filter.")
        return

    # Open output files
    logos_file = open('logos_found.csv', 'w', newline='', encoding='utf-8')
    emails_file = open('emails_found.csv', 'w', newline='', encoding='utf-8')
    logos_writer = csv.writer(logos_file)
    emails_writer = csv.writer(emails_file)
    logos_writer.writerow(['business_id', 'logo_url'])
    emails_writer.writerow(['business_id', 'email'])

    # Run scraping
    worker.start = time.time()
    print(f"\nStarting scrape... (ETA: ~{len(businesses) * 2 // 60} min)")

    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futures = [ex.submit(worker, b, scrape_logos, scrape_emails, args.delay)
                   for b in businesses]
        for f in as_completed(futures):
            try:
                r = f.result()
                if r:
                    if r['logo_url']:
                        logos_writer.writerow([r['business_id'], r['logo_url']])
                        logos_file.flush()
                    if r['email']:
                        emails_writer.writerow([r['business_id'], r['email']])
                        emails_file.flush()
            except Exception as e:
                print(f"  [ERROR]: {str(e)[:80]}", flush=True)

    logos_file.close()
    emails_file.close()

    elapsed = time.time() - worker.start
    print(f"\n{'='*60}")
    print(f"✅ Done in {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"{'='*60}")
    print(f"  Total scraped:   {stats['scraped']}")
    print(f"  Logos found:     {stats['logos_found']} → logos_found.csv")
    print(f"  Emails found:    {stats['emails_found']} → emails_found.csv")
    print(f"  Failed:          {stats['failed']}")

    print(f"\n📤 Upload logos_found.csv + emails_found.csv to the chat")
    print(f"   I'll import them to production DB for you.")

if __name__ == '__main__':
    main()
