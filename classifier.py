"""
NetWatch Classifier Engine
Uses Groq (llama-3.1-8b-instant) to detect drug trafficking signals.
Extracts maximum PII and seller intelligence from Reddit posts and comments.
"""

import os
import re
import json
import hashlib
from datetime import datetime, timezone
from groq import AsyncGroq

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.1-8b-instant"

SYSTEM_PROMPT = """You are an OSINT analyst for India's Narcotics Control Bureau (NCB).
Classify Reddit posts/comments for drug trafficking and extract ALL seller intelligence.

Classify into EXACTLY one label:
- DRUG_SALE: offering to sell/supply drugs (highest priority)
- DRUG_PURCHASE: seeking to buy drugs
- CODED_LANGUAGE: suspicious slang or coded terms suggesting trafficking
- DRUG_USE: personal use discussion only
- CLEAN: no drug-related content

Extract ALL of the following (empty array [] if not found):
- substances: drugs mentioned (cannabis, mdma, heroin, cocaine, meth, lsd, ketamine, opioids, fentanyl, tramadol, etc.)
- hinglish_flags: Hindi/Hinglish slang (maal, charas, smack, goli, brown sugar, nasha, ganja, etc.)
- location_hints: any city, state, country mentions (especially Indian cities)
- contact_handles: ANY @usernames, Telegram IDs, Discord tags, Wickr IDs, Signal handles, Reddit usernames offered as contact
- phone_numbers: any phone numbers including partial, formatted, or obfuscated (e.g. "call 98XXXXXX12", "+91-9812345678", "nine eight one two...")
- upi_ids: any UPI IDs (e.g. "pay@paytm", "name@okaxis", "number@ybl", "upi:XXXX")
- email_addresses: any email addresses mentioned
- pricing: any price mentions ("$50/g", "500 rs per gram", "bulk discount", "cheap", "wholesale")
- shipping_hints: delivery/shipping mentions ("stealth", "domestic", "discreet", "overnight", "PAN India", "all states")
- payment_methods: payment methods ("BTC", "crypto", "UPI", "Paytm", "cash", "Monero", "USDT", "Venmo")
- platform_links: external links, Telegram groups, WhatsApp links, dark web URLs, other platform mentions

Be aggressive in extraction — if something looks like it COULD be a contact method or identifier, include it.

Respond ONLY with a valid JSON array. No preamble, no markdown, no explanation.
[
  {
    "id": "<post_id>",
    "label": "<LABEL>",
    "confidence": <0.0-1.0>,
    "substances": [],
    "hinglish_flags": [],
    "location_hints": [],
    "contact_handles": [],
    "phone_numbers": [],
    "upi_ids": [],
    "email_addresses": [],
    "pricing": [],
    "shipping_hints": [],
    "payment_methods": [],
    "platform_links": [],
    "reason": "<one line>"
  }
]"""

# ─── REGEX EXTRACTORS (run on raw text as safety net) ───────────────────────

def _regex_extract(text: str) -> dict:
    """
    Regex-based PII extraction as a fallback/supplement to LLM extraction.
    Catches things the LLM might miss.
    """
    # Indian phone numbers: +91XXXXXXXXXX, 91XXXXXXXXXX, 9XXXXXXXXX, 8XXXXXXXXX, 7XXXXXXXXX
    phone_pattern = re.compile(
        r'(?:\+91[\s\-]?)?(?:91[\s\-]?)?[6-9]\d{9}|'
        r'\b[6-9]\d{4}[\s\-]?\d{5}\b'
    )

    # UPI IDs: anything@upi_handle
    upi_pattern = re.compile(
        r'[a-zA-Z0-9.\-_+]+@(?:paytm|okaxis|okhdfcbank|okicici|oksbi|ybl|axl|'
        r'ibl|apl|barodampay|centralbank|cnrb|csbpay|dbs|equitas|freecharge|'
        r'hsbc|idbi|idfc|ikwik|indus|juspay|kbl|kotak|lime|lvb|mahb|myairtel|'
        r'nsdl|pnb|pockets|postpaid|rbl|sc|sib|timecosmos|uboi|ubi|unionbank|'
        r'upi|vijb|waaxis|wpay|yapl)\b',
        re.IGNORECASE
    )

    # Emails
    email_pattern = re.compile(
        r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b'
    )

    # Telegram handles: @username or t.me/username
    telegram_pattern = re.compile(
        r'@[A-Za-z0-9_]{5,32}|t\.me/[A-Za-z0-9_]+|telegram\.me/[A-Za-z0-9_]+'
    )

    # WhatsApp links
    whatsapp_pattern = re.compile(
        r'wa\.me/\d+|whatsapp\.com/[^\s]+'
    )

    phones    = list(set(phone_pattern.findall(text)))
    upis      = list(set(upi_pattern.findall(text)))
    emails    = list(set(email_pattern.findall(text)))
    telegrams = list(set(telegram_pattern.findall(text)))
    whatsapps = list(set(whatsapp_pattern.findall(text)))

    return {
        "phone_numbers":  [p.strip() for p in phones],
        "upi_ids":        upis,
        "email_addresses": emails,
        "contact_handles": telegrams,
        "platform_links":  whatsapps,
    }


def _merge_intel(llm: dict, regex: dict) -> dict:
    """Merge LLM extraction with regex extraction, deduplicating."""
    merged = dict(llm)
    for field, values in regex.items():
        existing = set(merged.get(field, []))
        merged[field] = list(existing | set(values))
    return merged


# ─── CORE CLASSIFIER ────────────────────────────────────────────────────────

async def classify_batch(posts: list, batch_size: int = 15) -> list:
    if not posts:
        return []
    flagged = []
    for i in range(0, len(posts), batch_size):
        batch = posts[i:i + batch_size]
        results = await _classify_batch_call(batch)
        flagged.extend(results)
    return flagged


async def _classify_batch_call(posts: list) -> list:
    payload = [
        {
            "id":   p.get("id", f"post_{idx}"),
            "text": (p.get("text") or p.get("title", ""))[:800],
        }
        for idx, p in enumerate(posts)
    ]

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            temperature=0.1,
            max_tokens=4000,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": json.dumps(payload)}
            ]
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        classifications = json.loads(raw)

    except json.JSONDecodeError:
        return []
    except Exception as e:
        print(f"[Classifier] Groq call failed: {e}")
        return []

    post_lookup = {p.get("id", f"post_{idx}"): p for idx, p in enumerate(posts)}

    flagged = []
    for cls in classifications:
        if cls.get("label") == "CLEAN":
            continue

        post_id  = cls.get("id")
        original = post_lookup.get(post_id, {})
        text     = original.get("text") or original.get("title", "")

        # Merge LLM intel with regex extraction
        llm_intel = {
            "contact_handles":  cls.get("contact_handles", []),
            "phone_numbers":    cls.get("phone_numbers", []),
            "upi_ids":          cls.get("upi_ids", []),
            "email_addresses":  cls.get("email_addresses", []),
            "platform_links":   cls.get("platform_links", []),
        }
        regex_intel = _regex_extract(text)
        merged_intel = _merge_intel(llm_intel, regex_intel)

        flagged.append({
            # Post data
            "id":     post_id,
            "text":   text,
            "title":  original.get("title", ""),
            "author": original.get("author", "anonymous"),
            "url":    original.get("url", ""),
            "date":   original.get("date"),
            "type":   original.get("type", "post"),  # post or comment

            # Classification
            "label":      cls.get("label", "CODED_LANGUAGE"),
            "confidence": float(cls.get("confidence", 0.5)),
            "reason":     cls.get("reason", ""),

            # Drug intel
            "substances":     cls.get("substances", []),
            "hinglish_flags": cls.get("hinglish_flags", []),
            "location_hints": cls.get("location_hints", []),

            # Seller intel (LLM + regex merged)
            **merged_intel,
            "pricing":         cls.get("pricing", []),
            "shipping_hints":  cls.get("shipping_hints", []),
            "payment_methods": cls.get("payment_methods", []),

            # Evidence integrity
            "evidence_hash": _generate_evidence_hash(text, post_id),
            "archived_at":   datetime.now(timezone.utc).isoformat(),
        })

    return flagged


# ─── RISK SCORING ────────────────────────────────────────────────────────────

def compute_risk_score(total_posts: int, flagged_posts: list) -> float:
    if total_posts == 0 or not flagged_posts:
        return 0.0
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
    avg_severity  = weighted_sum / len(flagged_posts)
    score = min(flagged_ratio * avg_severity * 10 * 2.5, 10.0)
    return round(score, 2)


def risk_level(score: float) -> str:
    if score >= 8:   return "CRITICAL"
    elif score >= 6: return "HIGH"
    elif score >= 4: return "MEDIUM"
    elif score >= 2: return "LOW"
    else:            return "MINIMAL"


# ─── EVIDENCE HASH ───────────────────────────────────────────────────────────

def _generate_evidence_hash(text: str, post_id: str) -> str:
    raw = f"{post_id}::{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
