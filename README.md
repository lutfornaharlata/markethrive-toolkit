# MarketHrive Local Scraper Toolkit

এই toolkit দিয়ে আপনি আপনার কম্পিউটার থেকে business websites স্ক্র্যাপ করে logos + emails বের করতে পারবেন। Vercel-এর 60s timeout এর সমস্যা থাকবে না — আপনার মেশিনে যত খুশি তত চালাতে পারবেন।

## 📋 Setup (একবারই করতে হবে)

### Python ইনস্টল থাকলে শুধু dependencies ইনস্টল করুন:

```bash
pip install requests beautifulsoup4
```

Python না থাকলে: https://python.org থেকে ডাউনলোড করুন (Python 3.10+)।

---

## 🚀 কীভাবে চালাবেন

### Step 1: বর্তমান businesses লিস্ট ডাউনলোড করুন

```bash
python download_targets.py
```

এটি production DB থেকে সব businesses এর তালিকা ডাউনলোড করে `targets.csv` ফাইলে সেভ করবে।

### Step 2: Logos + Emails স্ক্র্যাপ করুন

```bash
# সব businesses
python scrape.py

# শুধু নির্দিষ্ট city
python scrape.py --city Birmingham

# শুধু নির্দিষ্ট niche
python scrape.py --niche roofing

# শুধু email দরকার
python scrape.py --emails-only

# শুধু লোগো দরকার
python scrape.py --logos-only

# Parallel threads (default: 8)
python scrape.py --threads 12
```

### Step 3: আউটপুট ফাইল দেখুন

স্ক্র্যাপিং শেষ হলে দুটি ফাইল তৈরি হবে:

- **`logos_found.csv`** — business_id, logo_url
- **`emails_found.csv`** — business_id, email

### Step 4: ফাইলগুলো আমাকে দিন

`logos_found.csv` এবং `emails_found.csv` ফাইল দুটি upload করুন এই চ্যাটে। আমি সরাসরি production DB-তে import করে দেব।

---

## ⚡ Tips

1. **Cloudflare-protected sites**: কিছু site 403 দেবে। সেগুলো skip হয়ে যাবে।

2. **Rate limiting**: Default 8 threads। খুব দ্রুত চালালে sites block করতে পারে।

3. **Email validation**: স্ক্রিপ্ট automatic ভাবে reject করবে sentry/wix/example emails।

4. **Resume**: স্ক্রিপ্ট চালানো থামিয়ে দিলে আবার চালালে নতুন করে শুরু হবে (append না)।

---

## 📁 ফাইল স্ট্রাকচার

```
local-scraper/
├── README.md              ← এই ফাইল
├── download_targets.py    ← targets.csv ডাউনলোড করে
├── scrape.py              ← মূল স্ক্র্যাপার
├── targets.csv            ← (auto-generated) business লিস্ট
├── logos_found.csv        ← (auto-generated) স্ক্র্যাপ করা logos
└── emails_found.csv       ← (auto-generated) স্ক্র্যাপ করা emails
```
