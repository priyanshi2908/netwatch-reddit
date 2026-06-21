"""
Reddit public JSON scraper — no API key, no auth, works in India.
Uses old.reddit.com + multiple fallback strategies to bypass 403 blocks.
"""
import httpx
import asyncio
import random
from typing import Optional

# Rotate through realistic browser user agents
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

def _headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    }

# Try multiple URL patterns — Reddit blocks some, not others
def _urls(subreddit: str, limit: int):
    return [
        f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}&raw_json=1",
        f"https://old.reddit.com/r/{subreddit}/hot.json?limit={limit}&raw_json=1",
        f"https://www.reddit.com/r/{subreddit}.json?limit={limit}&raw_json=1",
        f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}&raw_json=1",
    ]


async def scrape_subreddit(subreddit: str, limit: int = 50) -> dict:
    """
    Fetch posts from a public subreddit.
    Tries multiple URL patterns and user agents to bypass 403.
    Returns channel_info + list of posts.
    Raises ValueError for private/banned/nonexistent subs.
    """
    urls = _urls(subreddit, limit)
    last_status = None

    for url in urls:
        try:
            async with httpx.AsyncClient(
                timeout=20,
                follow_redirects=True,
                http2=False,
            ) as client:
                # Small delay to avoid rate limiting
                await asyncio.sleep(random.uniform(0.5, 1.5))
                resp = await client.get(url, headers=_headers())

            last_status = resp.status_code

            if resp.status_code == 404:
                raise ValueError(f"r/{subreddit} does not exist.")

            if resp.status_code == 200:
                data = resp.json()
                children = data.get("data", {}).get("children", [])

                if not children:
                    continue  # Try next URL pattern

                posts = []
                for child in children:
                    p = child.get("data", {})
                    text = p.get("selftext", "").strip()
                    # Use title if body is empty or removed
                    if not text or text in ("[removed]", "[deleted]"):
                        text = p.get("title", "")
                    posts.append({
                        "id": p.get("id"),
                        "title": p.get("title", ""),
                        "text": text,
                        "author": p.get("author", "anonymous"),
                        "url": f"https://reddit.com{p.get('permalink', '')}",
                        "date": p.get("created_utc"),
                        "score": p.get("score", 0),
                        "num_comments": p.get("num_comments", 0),
                    })

                channel_info = {
                    "title": f"r/{subreddit}",
                    "subscriber_count": data.get("data", {}).get("dist"),
                    "description": f"Public feed tracking for r/{subreddit}",
                }

                return {"channel_info": channel_info, "posts": posts}

        except ValueError:
            raise
        except Exception:
            continue  # Try next URL

    # All URLs failed
    if last_status == 403:
        raise ValueError(
            f"Reddit is blocking requests to r/{subreddit} from this IP. "
            "Try a VPN or use Reddit API credentials."
        )
    raise ValueError(f"Could not fetch r/{subreddit} (last status: {last_status}).")


async def get_osint_feed() -> list:
    """
    Powers the Live Intelligence Feed panel.
    Tries multiple subreddits and filters by drug-related keywords.
    """
    subreddits = ["worldnews", "news", "technology", "globalnews"]
    keywords = ["drug", "ndps", "ncb", "narcotics", "seized", "arrested", "trafficking", "smuggling", "cartel"]
    feed = []

    async def fetch_sub(sub):
        try:
            url = f"https://www.reddit.com/r/{sub}/new.json?limit=20&raw_json=1"
            async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
                await asyncio.sleep(random.uniform(0.2, 0.8))
                resp = await client.get(url, headers=_headers())
            if resp.status_code != 200:
                return []
            data = resp.json()
            children = data.get("data", {}).get("children", [])
            results = []
            for child in children:
                p = child.get("data", {})
                title = p.get("title", "")
                if any(kw.lower() in title.lower() for kw in keywords):
                    results.append({
                        "title": title,
                        "url": f"https://reddit.com{p.get('permalink', '')}",
                        "source": f"r/{sub}",
                        "created": p.get("created_utc"),
                    })
            return results
        except Exception:
            return []

    results = await asyncio.gather(*[fetch_sub(s) for s in subreddits])
    for r in results:
        feed.extend(r)

    return feed