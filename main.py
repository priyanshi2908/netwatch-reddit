from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

# Import your actual pipeline engines securely
from scraper import scrape_subreddit, get_osint_feed
from classifier import classify_batch, compute_risk_score, risk_level
from store import save_case, get_case, get_all_cases, get_stats

app = FastAPI(title="NetWatch API", version="1.0.0")

# Setup CORS to cleanly allow your local port 5500 frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "NetWatch API running", "version": "1.0.0"}

# ─────────────────────────────────────────
# DASHBOARD STATS
# ─────────────────────────────────────────

@app.get("/api/stats")
def dashboard_stats():
    """Powers the 4 stat cards on Command Center."""
    return get_stats()

# ─────────────────────────────────────────
# LIVE OSINT FEED
# ─────────────────────────────────────────

@app.get("/api/osint-feed")
async def osint_feed():
    """Powers the Live Intelligence Feed panel."""
    feed = await get_osint_feed()
    return {"feed": feed}

# ─────────────────────────────────────────
# PIPELINE BRIDGE DATA ENGINE
# ─────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    handle: str          # Subreddit name e.g. "opiates" or "r/Drugs"
    platform: str = "Reddit"

async def run_intel_pipeline(handle: str, platform: str):
    """Reusable ingestion worker for processing live community nodes."""
    clean_handle = handle.strip().lstrip("r/").lstrip("@").strip()
    if not clean_handle:
        raise HTTPException(status_code=400, detail="Handle is required.")

    # 1. Hit the public live internet endpoint 
    try:
        scraped = await scrape_subreddit(clean_handle, limit=50)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    channel_info = scraped["channel_info"]
    posts = scraped["posts"]

    # 2. Run OpenAI Content Classification
    flagged = await classify_batch(posts)

    # 3. Compute risk severity matrix
    score = compute_risk_score(len(posts), flagged)
    level = risk_level(score)

    # 4. Consolidate illicit substance variables
    all_substances = list({s for p in flagged for s in p.get("substances", [])})

    # 5. Bot score heuristics
    drug_sale_count = sum(1 for p in flagged if p["label"] == "DRUG_SALE")
    bot_score = min(int((drug_sale_count / max(len(posts), 1)) * 100 * 2), 99)

    case = {
        "channel_username": clean_handle,
        "channel_title": channel_info["title"],
        "platform": platform,
        "subscriber_count": channel_info.get("subscriber_count"),
        "description": channel_info.get("description", ""),
        "total_posts": len(posts),
        "flagged_count": len(flagged),
        "risk_score": score,
        "risk_level": level,
        "bot_score": bot_score,
        "substances": all_substances,
        "flagged_posts": flagged,
        "is_storefront_bot": bot_score > 70,
    }

    case_id = save_case(case)
    return {"case_id": case_id, **case}

# Support both endpoints natively to maintain total frontend compatibility
@app.post("/api/analyze")
async def analyze_channel(body: AnalyzeRequest):
    return await run_intel_pipeline(body.handle, body.platform)

@app.post("/api/scan")
async def scan_channel(body: AnalyzeRequest):
    res = await run_intel_pipeline(body.handle, body.platform)
    return {"status": "Success", "scanned_target": res}

# ─────────────────────────────────────────
# MONITORED CHANNELS GRID
# ─────────────────────────────────────────

@app.get("/api/channels")
def list_channels():
    cases = get_all_cases()
    return [
        {
            "id": c["id"],
            "channel_username": c["channel_username"],
            "channel_title": c["channel_title"],
            "platform": c.get("platform", "Reddit"),
            "subscriber_count": c.get("subscriber_count"),
            "total_posts": c["total_posts"],
            "flagged_count": c["flagged_count"],
            "risk_score": c["risk_score"],
            "risk_level": c["risk_level"],
            "bot_score": c.get("bot_score", 0),
            "substances": c.get("substances", []),
            "is_storefront_bot": c.get("is_storefront_bot", False),
        }
        for c in cases
    ]

@app.get("/api/channels/{case_id}")
def get_channel_detail(case_id: int):
    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found.")
    return case

# ─────────────────────────────────────────
# EVIDENCE VAULT
# ─────────────────────────────────────────

@app.get("/api/evidence")
def evidence_vault():
    cases = get_all_cases()
    evidence = []
    for c in cases:
        for post in c.get("flagged_posts", []):
            evidence.append({
                "case_id": c["id"],
                "channel": c["channel_username"],
                "platform": c.get("platform", "Reddit"),
                **post,
            })
    evidence.sort(key=lambda x: x.get("archived_at", ""), reverse=True)
    return evidence

# ─────────────────────────────────────────
# SUSPECT DOSSIERS
# ─────────────────────────────────────────

@app.get("/api/dossiers")
def suspect_dossiers():
    cases = get_all_cases()
    return [c for c in cases if c.get("risk_score", 0) >= 7]
