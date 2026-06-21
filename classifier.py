"""
NetWatch Classifier Engine
Uses GPT-4o-mini to detect drug trafficking signals in Reddit posts.
Handles Hinglish slang, coded language, and Indian drug market terminology.
"""

import os
import json
import hashlib
import asyncio
from datetime import datetime, timezone
from typing import Optional
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ─────────────────────────────────────────
# LABELS
# ─────────────────────────────────────────

LABELS = {
    "DRUG_SALE":      "Explicit offer to sell or supply controlled substances",
    "DRUG_PURCHASE":  "Request to buy or procure controlled substances",
    "DRUG_USE":       "Personal use discussion — lower priority, flag for context",
    "CODED_LANGUAGE": "Suspicious slang or coded terms suggesting trafficking",
    "CLEAN":          "No narcotics-related content detected",
}

SYSTEM_PROMPT = """You are an OSINT analyst for India's Narcotics Control Bureau (NCB).
Your job is to classify Reddit posts for drug trafficking signals.

Classify each post into EXACTLY one of these labels:
- DRUG_SALE: offering to sell/supply drugs (highest priority)
- DRUG_PURCHASE: seeking to buy drugs
- CODED_LANGUAGE: suspicious slang, coded terms, or evasive language suggesting trafficking
- DRUG_USE: personal use discussion only (not trafficking)
- CLEAN: no drug-related content

You must also extract:
- substances: list of drugs mentioned (use standard names: cannabis, mdma, heroin, cocaine, meth, lsd, ketamine, opioids, etc.)
- hinglish_flags: any Hindi/Hinglish slang terms that are suspicious (e.g. "maal", "charas", "smack", "goli")
- location_hints: any Indian city/state mentions

Indian context: watch for terms like maal, charas, ganja, smack, brown sugar, crystal, MD, molly, trips, tabs, weed, nasha.

Respond ONLY with a JSON array. No preamble, no markdown, no explanation.
Format:
[
  {
    "id": "<post_id>",
    "label": "<LABEL>",
    "confidence": <0.0-1.0>,
    "substances": ["<substance>"],
    "hinglish_flags": ["<term>"],
    "location_hints": ["<place>"],
    "reason": "<one line explanation>"
  }
]"""


# ─────────────────────────────────────────
# CORE CLASSIFIER
# ─────────────────────────────────────────

async def classify_batch(posts: list, batch_size: int = 20) -> list:
    """
    Classifies a list of posts in batches.
    Returns only flagged posts (non-CLEAN) with evidence hashes.
    """
    if not posts:
        return []

    flagged = []

    # Process in batches to stay within token limits
    for i in range(0, len(posts), batch_size):
        batch = posts[i:i + batch_size]
        batch_results = await _classify_batch_call(batch)
        flagged.extend(batch_results)

    return flagged


async def _classify_batch_call(posts: list) -> list:
    """Single GPT-4o-mini batch call for a subset of posts."""
    # Build compact post payload to save tokens
    payload = [
        {
            "id": p.get("id", f"post_{idx}"),
            "text": (p.get("text") or p.get("title", ""))[:500],  # Truncate long posts
        }
        for idx, p in enumerate(posts)
    ]

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,  # Low temp for consistent classification
            max_tokens=2000,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload)}
            ]
        )

        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if model adds them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        classifications = json.loads(raw)

    except json.JSONDecodeError:
        # Fallback: mark all as CLEAN if parsing fails
        return []
    except Exception as e:
        print(f"[Classifier] GPT call failed: {e}")
        return []

    # Build a lookup from post id → original post data
    post_lookup = {p.get("id", f"post_{idx}"): p for idx, p in enumerate(posts)}

    flagged = []
    for cls in classifications:
        if cls.get("label") == "CLEAN":
            continue

        post_id = cls.get("id")
        original = post_lookup.get(post_id, {})
        text = original.get("text") or original.get("title", "")

        flagged.append({
            # Original post fields
            "id": post_id,
            "text": text,
            "author": original.get("author", "anonymous"),
            "url": original.get("url", ""),
            "date": original.get("date"),

            # Classification output
            "label": cls.get("label", "CODED_LANGUAGE"),
            "confidence": float(cls.get("confidence", 0.5)),
            "substances": cls.get("substances", []),
            "hinglish_flags": cls.get("hinglish_flags", []),
            "location_hints": cls.get("location_hints", []),
            "reason": cls.get("reason", ""),

            # Evidence integrity hash (SHA-256 of post text + id)
            "evidence_hash": _generate_evidence_hash(text, post_id),
            "archived_at": datetime.now(timezone.utc).isoformat(),
        })

    return flagged


# ─────────────────────────────────────────
# RISK SCORING
# ─────────────────────────────────────────

def compute_risk_score(total_posts: int, flagged_posts: list) -> float:
    """
    Computes a 0–10 risk score for a channel.
    Factors: flagged ratio, label severity, average confidence.
    """
    if total_posts == 0 or not flagged_posts:
        return 0.0

    # Label severity weights
    severity = {
        "DRUG_SALE":      1.0,
        "DRUG_PURCHASE":  0.8,
        "CODED_LANGUAGE": 0.6,
        "DRUG_USE":       0.3,
    }

    weighted_sum = sum(
        severity.get(p.get("label", "DRUG_USE"), 0.3) * p.get("confidence", 0.5)
        for p in flagged_posts
    )

    flagged_ratio = len(flagged_posts) / total_posts
    avg_severity = weighted_sum / len(flagged_posts)

    # Score formula: ratio × severity × 10, capped at 10
    score = min(flagged_ratio * avg_severity * 10 * 2.5, 10.0)
    return round(score, 2)


def risk_level(score: float) -> str:
    """Maps numeric risk score to NCB threat level label."""
    if score >= 8:
        return "CRITICAL"
    elif score >= 6:
        return "HIGH"
    elif score >= 4:
        return "MEDIUM"
    elif score >= 2:
        return "LOW"
    else:
        return "MINIMAL"


# ─────────────────────────────────────────
# EVIDENCE INTEGRITY
# ─────────────────────────────────────────

def _generate_evidence_hash(text: str, post_id: str) -> str:
    """SHA-256 hash of post content for tamper-evident archiving."""
    raw = f"{post_id}::{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()