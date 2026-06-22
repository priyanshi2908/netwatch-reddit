# NetWatch — AI-Powered Drug Trafficking Intelligence Platform

## What is NetWatch?

NetWatch is a real-time OSINT (Open Source Intelligence) platform that detects drug trafficking signals on public Reddit communities. It uses AI classification to flag posts and comments, extract seller intelligence (contact handles, pricing, payment methods, UPI IDs, phone numbers), and archive tamper-evident evidence with SHA-256 hashing.

**Pipeline:**
```
Arctic Shift (Reddit Archive API)
    → Posts + Comments Scraped
        → Groq LLaMA 3.1 8B Classification
            → Seller Intel Extracted (PII, pricing, contacts)
                → SQLite Evidence Vault (SHA-256 hashed)
                    → FastAPI Backend
                        → Live Dashboard (HTML/Tailwind)
```

---

## Features

- **Real Reddit data** via Arctic Shift public API — no Reddit account needed, works from any IP
- **AI classification** using Groq LLaMA 3.1 8B — labels posts as DRUG_SALE, DRUG_PURCHASE, CODED_LANGUAGE, DRUG_USE
- **Dual scraping** — fetches both posts AND comments (comments have more PII)
- **PII extraction** — phone numbers, UPI IDs, emails, Telegram handles via LLM + regex
- **Evidence vault** — every flagged post archived with SHA-256 hash for court admissibility
- **Risk scoring** — 0–10 risk score per subreddit with CRITICAL/HIGH/MEDIUM/LOW levels
- **Hinglish detection** — flags Indian drug slang (maal, charas, smack, goli, brown sugar)
- **Live dashboard** — auto-refreshes every 5 seconds, filter by label or PII presence

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| AI Classifier | Groq API (llama-3.1-8b-instant) |
| Data Source | Arctic Shift Reddit Archive API |
| Database | SQLite (via Python stdlib) |
| Frontend | Vanilla HTML + Tailwind CSS v4 |
| Evidence Integrity | SHA-256 (hashlib) |
| HTTP Client | httpx (async) |

---

## Project Structure

```
netwatch-reddit/
├── backend/
│   ├── main.py           # FastAPI app, all API routes
│   ├── scraper.py        # Arctic Shift Reddit scraper (posts + comments)
│   ├── classifier.py     # Groq LLM classifier + regex PII extractor
│   ├── store.py          # SQLite store (cases, evidence, stats)
│   ├── requirements.txt  # Python dependencies
│   ├── .env              # API keys (never commit this)
│   └── netwatch.db       # SQLite DB (auto-created on first run)
└── frontend/
    └── index.html        # Dashboard UI
```

---

## Prerequisites

- Python 3.11 or 3.12 (not 3.13/3.14 — pydantic-core build fails)
- A free [Groq API key](https://console.groq.com/keys)
- Node.js (optional, for `npx serve`)

---

## Setup & Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/netwatch-reddit.git
cd netwatch-reddit
```

### 2. Create a virtual environment with Python 3.11 or 3.12

```bash
# Check available versions
python3.11 --version || python3.12 --version

# Create venv
python3.11 -m venv venv
source venv/bin/activate      # Mac/Linux
venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 4. Set up environment variables

```bash
cp .env.example .env
```

Edit `.env`:
```
GROQ_API_KEY=gsk_your_key_here
```

Get your free Groq key at: https://console.groq.com/keys

### 5. Start the backend

```bash
uvicorn main:app --reload --port 8000
```

You should see:
```
INFO: Application startup complete.
INFO: Uvicorn running on http://127.0.0.1:8000
```

### 6. Open the frontend

Option A — VS Code Live Server (recommended):
- Right-click `frontend/index.html` → **Open with Live Server**

Option B — npx serve:
```bash
cd ../frontend
npx serve . --port 5500
```

Then open: **http://localhost:5500**

---

## Usage

1. Open the dashboard at `http://localhost:5500`
2. Click **"Force Scraping Run"**
3. Enter a subreddit name (e.g. `opiates`, `heroin`, `darknetmarkets`, `IndianEnts`)
4. Wait 10–20 seconds for the AI to classify posts and comments
5. View flagged results in **Command Center** (stats + channel table)
6. Click **Evidence Vault** in the sidebar to see full intel cards
7. Use the filter dropdowns to show only **PII Found** entries

### Recommended subreddits to scan

| Subreddit | Focus |
|---|---|
| `opiates` | Opioid discussion, US/international |
| `heroin` | High signal-to-noise for trafficking |
| `darknetmarkets` | Marketplace discussion, vendor intel |
| `IndianEnts` | India-specific cannabis community |
| `cocaine` | Cocaine sale/purchase signals |
| `darknet` | Dark web access + market links |

---

## API Endpoints

```
GET  /                      # Health check
GET  /api/stats             # Dashboard stat cards
GET  /api/evidence          # All flagged posts with intel
GET  /api/channels          # All scanned subreddits
GET  /api/channels/{id}     # Single channel detail
POST /api/analyze           # Trigger a new scan
POST /api/scan              # Alias for /api/analyze
GET  /api/dossiers          # High risk channels (score ≥ 7)
```

### Example scan request

```bash
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"handle": "opiates", "platform": "Reddit"}'
```

---

## Evidence Vault

Every flagged post is stored with:

| Field | Description |
|---|---|
| `evidence_hash` | SHA-256 of post content + ID |
| `archived_at` | UTC timestamp of archival |
| `label` | AI classification label |
| `confidence` | Model confidence (0–1) |
| `phone_numbers` | Extracted Indian phone numbers |
| `upi_ids` | UPI payment IDs (name@paytm etc.) |
| `email_addresses` | Email addresses found |
| `contact_handles` | Telegram/Discord/Wickr handles |
| `pricing` | Price mentions |
| `payment_methods` | BTC, UPI, Paytm, cash etc. |
| `shipping_hints` | Delivery/stealth mentions |
| `platform_links` | Links to other platforms |

---

## Environment Variables

| Variable | Description | Required |
|---|---|---|
| `GROQ_API_KEY` | Groq API key for LLaMA classification | Yes |
| `NETWATCH_DB` | SQLite DB path (default: `netwatch.db`) | No |

---

## Troubleshooting

**`pydantic-core` build fails on install**
You're on Python 3.13 or 3.14. Use Python 3.11 or 3.12:
```bash
brew install python@3.11
python3.11 -m venv venv
```

**`ModuleNotFoundError: dotenv`**
```bash
pip install python-dotenv
```

**Arctic Shift returns 400**
The `limit` parameter exceeds 100. The scraper already caps at 100 — make sure you're using the latest `scraper.py`.

**All stats are 0 after scan**
Check the uvicorn terminal for Groq errors. Usually means `GROQ_API_KEY` is missing from `.env`.

**`[removed]` posts in Evidence Vault**
Delete the old database and rescan — the old scraper didn't filter removed posts:
```bash
rm backend/netwatch.db
```

