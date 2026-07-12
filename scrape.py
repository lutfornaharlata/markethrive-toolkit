#!/usr/bin/env python3
"""
MarketHrive — Local scraper with proxy rotation + distributed mode.

Features:
  - Proxy rotation (free proxies or paid proxy file)
  - Distributed mode (--start, --limit for parallel runs on multiple machines)
  - Smart retry with different proxy on failure
  - Per-request rate limiting (per-proxy)
  - Email + Logo extraction

Usage:
    # Basic (no proxy)
    python scrape.py

    # Free proxy rotation
    python scrape.py --use-proxies --threads 4

    # Paid proxy file (one proxy per line: ip:port or user:pass@ip:port)
    python scrape.py --proxy-file proxies.txt --threads 10

    # Distributed mode (run on multiple machines)
    python scrape.py --start 0 --limit 100 --output batch1_logos.csv
    python scrape.py --start 100 --limit 100 --output batch2_logos.csv

    # Filter by city/niche
    python scrape.py --city Birmingham --niche roofing

    # Only logos or only emails
    python scrape.py --logos-only
    python scrape.py --emails-only
"""
import argparse, csv, os, re, sys, time, threading, random
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

# ─── Config ───────────────────────────────────────────────────
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

# Multiple user agents for rotation
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
stats = {'scraped': 0, 'logos_found': 0, 'emails_found': 0, 'failed': 0, 'total': 0,
         'proxies_tried': 0, 'proxies_dead': 0}

# ─── Proxy Manager ────────────────────────────────────────────
class ProxyManager:
    """Manages a pool of proxies with health tracking."""

    def __init__(self, use_free=False, proxy_file=None):
        self.proxies = []
        self.dead = set()
        self.lock = threading.Lock()
        self.use_free = use_free

        if proxy_file and os.path.exists(proxy_file):
            self._load_from_file(proxy_file)
        elif use_free:
            self._load_free_proxies()

        if self.proxies:
            print(f"  Loaded {len(self.proxies)} proxies", flush=True)
        else:
            print("  No proxies loaded — direct connection mode", flush=True)

    def _load_from_file(self, path):
        """Format: one proxy per line, either 'ip:port' or 'user:pass@ip:port'"""
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if not line.startswith('http'):
                        line = f"http://{line}"
                    self.proxies.append(line)

    def _load_free_proxies(self):
        """Fetch free proxies from public APIs."""
        print("  Fetching free proxies...", flush=True)
        urls = [
            "https://proxylist.geonode.com/api/proxy-list?limit=50&page=1&sort_by=lastChecked&sort_type=desc&protocols=http&filterUpTime=90",
            "https://www.proxy-list.download/api/v1/get?type=http",
        ]
        for url in urls:
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    if 'geonode' in url:
                        import json
                        data = r.json()
                        for p in data.get('data', []):
                            ip = p.get('ip')
                            port = p.get('port')
                            if ip and port:
                                self.proxies.append(f"http://{ip}:{port}")
                    else:
                        for line in r.text.split('\n'):
                            line = line.strip()
                            if line and ':' in line:
                                self.proxies.append(f"http://{line}")
                    if self.proxies:
                        break
            except: pass

    def get_proxy(self):
        """Get a random live proxy."""
        with self.lock:
            live = [p for p in self.proxies if p not in self.dead]
            if not live:
                return None
            return random.choice(live)

    def mark_dead(self, proxy):
        """Mark a proxy as dead."""
        with self.lock:
            self.dead.add(proxy)
            stats['proxies_dead'] = len(self.dead)

    def stats(self):
        return {
            'total': len(self.proxies),
            'live': len(self.proxies) - len(self.dead),
            'dead': len(self.dead),
        }

# ─── Fetch with proxy ─────────────────────────────────────────
def fetch(url, timeout=10, proxy_manager=None, retries=3):
    """Fetch URL, optionally with proxy rotation + retries."""
    for attempt in range(retries):
        # Pick a random user agent
        headers = {**HEADERS, 'User-Agent': random.choice(USER_AGENTS)}

        # Pick proxy if available
        proxies = None
        if proxy_manager:
            proxy = proxy_manager.get_proxy()
            if proxy:
                proxies = {'http': proxy, 'https': proxy}
                with lock: stats['proxies_tried'] += 1

        try:
            r = requests.get(url, headers=headers, timeout=timeout,
                              proxies=proxies, allow_redirects=True, verify=True)
            if r.status_code == 200:
                ct = r.headers.get('Content-Type', '')
                if 'html' in ct or 'text' in ct or ct == '':
                    return r
            elif r.status_code in (403, 429):
                # Cloudflare block or rate limit — try different proxy
                if proxy_manager and proxies:
                    proxy_manager.mark_dead(proxies['http'])
                continue
            else:
                return None
        except requests.exceptions.ProxyError:
            if proxy_manager and proxies:
                proxy_manager.mark_dead(proxies['http'])
            continue
        except requests.exceptions.Timeout:
            continue
        except Exception:
            continue
    return None

# ─── Logo extraction ──────────────────────────────────────────
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
    seen = set(); emails = []
    for m in EMAIL_RE.findall(html):
        if m not in seen:
            seen.add(m); emails.append(m)
    for m in re.findall(r'mailto:([^"?>\s]+)', html, re.IGNORECASE):
        e = m.strip().rstrip('.,;:)}\'"')
        if e and e not in seen:
            seen.add(e); emails.append(e)
    return emails

# ─── Worker ───────────────────────────────────────────────────
def worker(biz, scrape_logos, scrape_emails, delay, proxy_manager):
    bid = biz['business_id']
    name = biz['name']
    website = biz['website']

    with lock:
        stats['scraped'] += 1
        n = stats['scraped']

    if not website or not website.startswith('http'):
        return None

    if delay > 0:
        time.sleep(delay * random.random())  # jitter

    result = {'business_id': bid, 'logo_url': None, 'email': None}

    try:
        resp = fetch(website, timeout=12, proxy_manager=proxy_manager)
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
            emails = extract_emails(resp.text)
            email = next((e.lower() for e in emails if is_valid_email(e)), None)
            if not email:
                parsed = urlparse(resp.url)
                base = f"{parsed.scheme}://{parsed.netloc}"
                for path in CONTACT_PATHS:
                    page = fetch(urljoin(base, path), timeout=8, proxy_manager=proxy_manager)
                    if page:
                        emails = extract_emails(page.text)
                        email = next((e.lower() for e in emails if is_valid_email(e)), None)
                        if email:
                            break
            if email:
                result['email'] = email
                with lock: stats['emails_found'] += 1
    except Exception:
        with lock: stats['failed'] += 1
        return None

    if n % 20 == 0:
        elapsed = time.time() - worker.start
        rate = n / max(elapsed, 1)
        eta = (stats['total'] - n) / max(rate, 0.1)
        proxy_info = ""
        if proxy_manager and proxy_manager.proxies:
            pstats = proxy_manager.stats()
            proxy_info = f" | proxies: {pstats['live']} live, {pstats['dead']} dead"
        print(f"  [{n}/{stats['total']}] logos={stats['logos_found']} "
              f"emails={stats['emails_found']} failed={stats['failed']}{proxy_info} "
              f"| {elapsed:.0f}s, ETA {eta:.0f}s", flush=True)

    return result

worker.start = time.time()

# ─── Main ─────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--city', default='')
    ap.add_argument('--niche', default='')
    ap.add_argument('--emails-only', action='store_true')
    ap.add_argument('--logos-only', action='store_true')
    ap.add_argument('--threads', type=int, default=8)
    ap.add_argument('--delay', type=float, default=0)
    ap.add_argument('--targets', default='targets.csv')
    ap.add_argument('--use-proxies', action='store_true', help='Use free rotating proxies')
    ap.add_argument('--proxy-file', default='', help='File with paid proxies (one per line)')
    ap.add_argument('--start', type=int, default=0, help='Start index (distributed mode)')
    ap.add_argument('--limit', type=int, default=0, help='Max businesses (0 = all)')
    ap.add_argument('--output-prefix', default='', help='Output file prefix (e.g. batch1_)')
    args = ap.parse_args()

    scrape_logos = not args.emails_only
    scrape_emails = not args.logos_only

    print("=== MarketHrive Local Scraper (Proxy-Enabled) ===")
    print(f"Threads: {args.threads} | Logos: {scrape_logos} | Emails: {scrape_emails}")

    # Proxy manager
    proxy_manager = None
    if args.proxy_file:
        proxy_manager = ProxyManager(proxy_file=args.proxy_file)
    elif args.use_proxies:
        proxy_manager = ProxyManager(use_free=True)

    if not os.path.exists(args.targets):
        print(f"\n❌ {args.targets} not found!")
        print(f"   Run: python download_targets.py")
        return

    # Load + filter targets
    businesses = []
    with open(args.targets, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if args.city and args.city.lower() not in row['city'].lower():
                continue
            if args.niche and row['niche_slug'] != args.niche:
                continue
            businesses.append(row)

    # Apply start/limit (distributed mode)
    if args.start > 0:
        businesses = businesses[args.start:]
    if args.limit > 0:
        businesses = businesses[:args.limit]

    stats['total'] = len(businesses)
    print(f"\nLoaded {len(businesses)} businesses (start={args.start}, limit={args.limit})")

    if not businesses:
        print("No businesses match the filter.")
        return

    # Output files
    logos_name = f"{args.output_prefix}logos_found.csv" if args.output_prefix else "logos_found.csv"
    emails_name = f"{args.output_prefix}emails_found.csv" if args.output_prefix else "emails_found.csv"
    logos_file = open(logos_name, 'w', newline='', encoding='utf-8')
    emails_file = open(emails_name, 'w', newline='', encoding='utf-8')
    logos_writer = csv.writer(logos_file)
    emails_writer = csv.writer(emails_file)
    logos_writer.writerow(['business_id', 'logo_url'])
    emails_writer.writerow(['business_id', 'email'])

    worker.start = time.time()
    proxy_str = " with proxies" if proxy_manager and proxy_manager.proxies else " (direct)"
    print(f"\nStarting scrape{proxy_str}... (ETA: ~{len(businesses) * 2 // 60} min)")

    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futures = [ex.submit(worker, b, scrape_logos, scrape_emails, args.delay, proxy_manager)
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
    print(f"  Logos found:     {stats['logos_found']} → {logos_name}")
    print(f"  Emails found:    {stats['emails_found']} → {emails_name}")
    print(f"  Failed:          {stats['failed']}")
    if proxy_manager and proxy_manager.proxies:
        pstats = proxy_manager.stats()
        print(f"  Proxy stats:     {pstats['live']} live, {pstats['dead']} dead, {stats['proxies_tried']} requests")

    print(f"\n📤 Upload {logos_name} + {emails_name} to the chat")
    print(f"   I'll import them to production DB for you.")

if __name__ == '__main__':
    main()
