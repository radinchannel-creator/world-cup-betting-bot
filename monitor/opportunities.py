from datetime import datetime, timezone, timedelta
import requests

from monitor.news import get_injury_news, INJURY_KEYWORDS

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"

BIG_TEAMS = {
    "france", "brazil", "germany", "spain", "england", "argentina",
    "portugal", "netherlands", "italy", "belgium", "croatia", "uruguay",
    "morocco", "japan", "south korea", "mexico", "usa", "united states",
    "norway", "colombia", "switzerland", "senegal", "egypt",
}


def _get_upcoming_games(days: int = 3) -> list:
    games = []
    for i in range(days + 1):
        date = (datetime.now(timezone.utc) + timedelta(days=i)).strftime("%Y%m%d")
        try:
            r = requests.get(SCOREBOARD, params={"dates": date}, timeout=10)
            for event in r.json().get("events", []):
                if event.get("status", {}).get("type", {}).get("state") != "pre":
                    continue
                comp = event.get("competitions", [{}])[0]
                teams = comp.get("competitors", [])
                home = next(
                    (t["team"]["displayName"] for t in teams if t["homeAway"] == "home"), ""
                )
                away = next(
                    (t["team"]["displayName"] for t in teams if t["homeAway"] == "away"), ""
                )
                games.append({
                    "game_id": event["id"],
                    "home": home,
                    "away": away,
                    "kickoff": event.get("date", ""),
                    "name": f"{home} vs {away}",
                })
        except Exception:
            pass
    return games


def _has_injury_news(news_items: list) -> bool:
    return any(
        any(k in item.get("title", "").lower() for k in INJURY_KEYWORDS)
        for item in news_items
    )


def _build_hints(game: dict, news: list, hours_out: float) -> list:
    hints = []

    injury_news = [
        n for n in news
        if any(k in n.get("title", "").lower() for k in INJURY_KEYWORDS)
    ]
    if injury_news:
        hints.append("injury/suspension news — check lineup before betting")

    home_l = game["home"].lower()
    away_l = game["away"].lower()
    home_big = any(t in home_l for t in BIG_TEAMS)
    away_big = any(t in away_l for t in BIG_TEAMS)

    if home_big and not away_big:
        hints.append(f"{game['home']} heavy home favorite — check ML or O1.5")
    elif away_big and not home_big:
        hints.append(f"{game['away']} strong away side — DNB for {game['home']} underdog value")
    elif home_big and away_big:
        hints.append("big-team clash — U2.5 goals often value in knockouts")
    else:
        hints.append("even match — U2.5 or DNB for either side may have EV")

    if hours_out <= 6:
        hints.append(f"kicks off in {hours_out:.0f}h — lineups likely confirmed, check now")
    elif hours_out <= 24:
        hints.append(f"kicks off in {hours_out:.0f}h — worth watching injury updates")

    return hints


def find_opportunities(existing_team_pairs: set) -> list:
    """
    existing_team_pairs: set of (home_lower, away_lower) tuples for already-covered games.
    Returns list of opportunity dicts for upcoming uncovered games.
    """
    upcoming = _get_upcoming_games(days=3)
    opportunities = []

    for game in upcoming:
        pair = (game["home"].lower(), game["away"].lower())
        if pair in existing_team_pairs:
            continue

        ko_str = game["kickoff"]
        if not ko_str:
            continue

        try:
            ko = datetime.fromisoformat(ko_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        hours_out = (ko - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours_out < 1 or hours_out > 72:
            continue

        news = get_injury_news(game["home"], game["away"])
        hints = _build_hints(game, news, hours_out)

        opportunities.append({
            "game": game,
            "hours_out": hours_out,
            "news": news[:3],
            "hints": hints,
        })

    return opportunities
