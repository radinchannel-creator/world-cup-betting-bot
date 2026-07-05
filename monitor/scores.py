import requests
from datetime import datetime, timezone
from typing import Optional

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/summary"


def get_live_score(
    game_id: Optional[str],
    home: str,
    away: str,
) -> Optional[dict]:
    if game_id:
        data = _fetch_summary(game_id)
        if data:
            return data
    return _search_scoreboard(home, away)


def discover_game_id(home: str, away: str) -> Optional[str]:
    for offset in range(3):
        from datetime import timedelta
        date = (datetime.now(timezone.utc) + timedelta(days=offset)).strftime("%Y%m%d")
        try:
            r = requests.get(SCOREBOARD_URL, params={"dates": date}, timeout=10)
            if r.status_code != 200:
                continue
            for event in r.json().get("events", []):
                name = event.get("name", "").lower()
                if home.lower() in name or away.lower() in name:
                    return event["id"]
        except Exception:
            continue
    return None


def _fetch_summary(game_id: str) -> Optional[dict]:
    try:
        r = requests.get(SUMMARY_URL, params={"event": game_id}, timeout=10)
        if r.status_code != 200:
            return None
        return _parse_summary(r.json())
    except Exception:
        return None


def _search_scoreboard(home: str, away: str) -> Optional[dict]:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    try:
        r = requests.get(SCOREBOARD_URL, params={"dates": today}, timeout=10)
        if r.status_code != 200:
            return None
        for event in r.json().get("events", []):
            name = event.get("name", "").lower()
            if home.lower() in name or away.lower() in name:
                return _parse_event(event)
    except Exception:
        pass
    return None


def _parse_summary(data: dict) -> Optional[dict]:
    try:
        header = data.get("header", {})
        comps = header.get("competitions", [{}])
        return _parse_competition(comps[0] if comps else {})
    except Exception:
        return None


def _parse_event(event: dict) -> Optional[dict]:
    try:
        comp = event.get("competitions", [{}])[0]
        return _parse_competition(comp)
    except Exception:
        return None


def _parse_competition(comp: dict) -> dict:
    competitors = comp.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})

    status = comp.get("status", {})
    status_type = status.get("type", {})

    goals = []
    for detail in comp.get("details", []):
        dtype = detail.get("type", {}).get("text", "").lower()
        if "goal" in dtype and "own goal" not in dtype:
            scorers = [
                a.get("displayName", "")
                for a in detail.get("athletesInvolved", [])
            ]
            goals.append({
                "time": detail.get("clock", {}).get("displayValue", ""),
                "team": detail.get("team", {}).get("displayName", ""),
                "scorers": scorers,
            })

    return {
        "state": status_type.get("state", "pre"),
        "clock": status.get("displayClock", ""),
        "period": status.get("period", 0),
        "home_team": home.get("team", {}).get("displayName", ""),
        "away_team": away.get("team", {}).get("displayName", ""),
        "home_score": int(home.get("score", 0) or 0),
        "away_score": int(away.get("score", 0) or 0),
        "goals": goals,
        "completed": status_type.get("completed", False),
    }
