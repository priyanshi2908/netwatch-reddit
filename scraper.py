"""
NetWatch Reddit Scraper — Arctic Shift API.
Scrapes BOTH posts AND comments for maximum intel coverage.
Filters removed/deleted content aggressively.
"""
import httpx
import asyncio

BASE = "https://arctic-shift.photon-reddit.com/api"

HEADERS = {
    "User-Agent": "NetWatch-LEA/1.0 (Law Enforcement Research Tool)",
    "Accept": "application/json",
}

OSINT_SUBREDDITS = ["worldnews", "news", "india", "technology"]
DRUG_KEYWORDS = [
    "drug", "ndps", "ncb", "narcotics", "seized", "arrested",
    "trafficking", "smuggling", "cartel", "meth", "cocaine",
    "heroin", "cannabis", "ganja", "charas", "mdma", "weed"
]
REMOVED_MARKERS = {"[removed]", "[deleted]", "", " "}


def _is_valid_text(text: str) -> bool:
    if not text:
        return False
    cleaned = text.strip()
    return cleaned not in REMOVED_MARKERS and len(cleaned) >= 20


async def _fetch_posts(subreddit: str) -> list:
    """Fetch posts from Arctic Shift (max 100)."""
    url = f"{BASE}/posts/search"
    params = {"subreddit": subreddit, "limit": 100, "sort": "desc"}

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, params=params, headers=HEADERS)

    if resp.status_code != 200:
        raise ValueError(f"Arctic Shift posts returned {resp.status_code} for r/{subreddit}.")

    data = resp.json()
    if data.get("error"):
        raise ValueError(f"Arctic Shift error: {data['error']}")

    posts = []
    for p in (data.get("data") or []):
        selftext = (p.get("selftext") or "").strip()
        title    = (p.get("title") or "").strip()

        if _is_valid_text(selftext):
            text = selftext
        elif _is_valid_text(title):
            text = title
        else:
            continue

        posts.append({
            "id":           p.get("id", ""),
            "title":        title,
            "text":         text,
            "author":       p.get("author", "anonymous"),
            "url":          f"https://reddit.com{p.get('permalink', '')}",
            "date":         p.get("created_utc"),
            "score":        p.get("score", 0),
            "num_comments": p.get("num_comments", 0),
            "type":         "post",
        })

    return posts


async def _fetch_comments(subreddit: str) -> list:
    """Fetch comments from Arctic Shift — where sellers drop PII."""
    url = f"{BASE}/comments/search"
    params = {"subreddit": subreddit, "limit": 100, "sort": "desc"}

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=HEADERS)

        if resp.status_code != 200:
            return []  # Comments endpoint might not exist for all subs

        data = resp.json()
        if data.get("error"):
            return []

        comments = []
        for c in (data.get("data") or []):
            body = (c.get("body") or "").strip()
            if not _is_valid_text(body):
                continue

            comments.append({
                "id":     c.get("id", ""),
                "title":  f"[Comment] {body[:80]}...",
                "text":   body,
                "author": c.get("author", "anonymous"),
                "url":    f"https://reddit.com{c.get('permalink', '')}",
                "date":   c.get("created_utc"),
                "score":  c.get("score", 0),
                "type":   "comment",
            })

        return comments

    except Exception:
        return []


async def scrape_subreddit(subreddit: str, limit: int = 50) -> dict:
    """
    Fetches both posts AND comments from a subreddit.
    Returns combined list filtered for valid content.
    """
    # Fetch posts and comments concurrently
    posts_task    = asyncio.create_task(_fetch_posts(subreddit))
    comments_task = asyncio.create_task(_fetch_comments(subreddit))

    posts    = await posts_task
    comments = await comments_task

    # Combine: posts first, then comments
    combined = posts + comments

    if not combined:
        raise ValueError(
            f"r/{subreddit} returned no valid content. "
            "All posts may be removed. Try: heroin, cocaine, darknetmarkets, IndianEnts"
        )

    # Deduplicate by id
    seen = set()
    unique = []
    for item in combined:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)

    channel_info = {
        "title":            f"r/{subreddit}",
        "subscriber_count": None,
        "description":      f"Arctic Shift feed for r/{subreddit} — {len(posts)} posts + {len(comments)} comments",
    }

    print(f"[Scraper] r/{subreddit}: {len(posts)} posts + {len(comments)} comments = {len(unique)} total")

    return {"channel_info": channel_info, "posts": unique[:limit*2]}


async def get_osint_feed() -> list:
    """Powers the Live Intelligence Feed panel."""
    feed = []

    async def fetch_sub(sub):
        try:
            url = f"{BASE}/posts/search"
            params = {"subreddit": sub, "limit": 30, "sort": "desc"}
            async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
                resp = await client.get(url, params=params, headers=HEADERS)
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = []
            for p in (data.get("data") or []):
                title = (p.get("title") or "").strip()
                if not _is_valid_text(title):
                    continue
                if any(kw.lower() in title.lower() for kw in DRUG_KEYWORDS):
                    results.append({
                        "title":   title,
                        "url":     f"https://reddit.com{p.get('permalink', '')}",
                        "source":  f"r/{sub}",
                        "created": p.get("created_utc"),
                    })
            return results
        except Exception:
            return []

    results = await asyncio.gather(*[fetch_sub(s) for s in OSINT_SUBREDDITS])
    for r in results:
        feed.extend(r)

    return feed
