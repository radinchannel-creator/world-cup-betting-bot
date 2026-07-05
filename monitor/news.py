import email.utils
import feedparser
from datetime import datetime, timezone, timedelta
from typing import List, Optional

INJURY_KEYWORDS = {
    "injur", "suspend", "doubt", "ruled out", "lineup",
    "starting xi", "fit", "sidelined", "out for", "misses",
    "unavailable", "knock", "muscle", "hamstring", "thigh"
}


def get_injury_news(team1: str, team2: str) -> List[dict]:
    query = f"{team1} {team2} World Cup 2026 injury lineup"
    url = (
        "https://news.google.com/rss/search"
        f"?q={query.replace(' ', '+')}"
        "&hl=en-US&gl=US&ceid=US:en"
    )
    items: List[dict] = []
    try:
        feed = feedparser.parse(url)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
        for entry in feed.entries[:15]:
            published = _parse_date(entry.get("published", ""))
            if published and published < cutoff:
                continue
            title = entry.get("title", "").lower()
            if any(kw in title for kw in INJURY_KEYWORDS):
                items.append({
                    "title": entry.get("title", ""),
                    "published": entry.get("published", ""),
                    "source": entry.get("source", {}).get("title", ""),
                })
            if len(items) >= 3:
                break
    except Exception:
        pass
    return items


def _parse_date(date_str: str) -> Optional[datetime]:
    try:
        parsed = email.utils.parsedate(date_str)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    except Exception:
        pass
    return None
