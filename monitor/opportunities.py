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

TIER_STAKES = {"S": 10.0, "A": 8.0, "B": 6.0, "C": 4.0}


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


def _suggest_bet(game: dict, news: list) -> dict:
    """Return bet_type, selection, estimated_odds, tier, estimated_prob based on matchup."""
    home_l = game["home"].lower()
    away_l = game["away"].lower()
    home_big = any(t in home_l for t in BIG_TEAMS)
    away_big = any(t in away_l for t in BIG_TEAMS)
    has_injury = _has_injury_news(news)

    if home_big and not away_big:
        # Strong home favourite — ML, bump to A if opponent injured
        tier = "A" if has_injury else "B"
        return {
            "bet_type": "ml",
            "selection": game["home"],
            "estimated_odds": 1.55,
            "estimated_prob": 0.68,
            "tier": tier,
        }
    elif away_big and not home_big:
        # Strong away side — DNB for home underdog (value play)
        return {
            "bet_type": "dnb",
            "selection": game["home"],
            "estimated_odds": 2.00,
            "estimated_prob": 0.50,
            "tier": "B",
        }
    elif home_big and away_big:
        # Big-team knockout clash — U2.5 goals
        return {
            "bet_type": "under_goals",
            "selection": "Under",
            "line": 2.5,
            "estimated_odds": 1.70,
            "estimated_prob": 0.60,
            "tier": "B",
        }
    else:
        # Even match — DNB home side
        return {
            "bet_type": "dnb",
            "selection": game["home"],
            "estimated_odds": 1.85,
            "estimated_prob": 0.50,
            "tier": "C",
        }


def _build_notes(game: dict, news: list, suggestion: dict, hours_out: float) -> str:
    parts = [f"Auto-detected. KO in {hours_out:.0f}h."]
    if _has_injury_news(news):
        parts.append("Injury/suspension news found — check lineup.")
    parts.append(f"Suggested: {suggestion['bet_type'].upper()} {suggestion['selection']} @ est. {suggestion['estimated_odds']}.")
    return " ".join(parts)


def find_opportunities(existing_team_pairs: set, next_bet_id: int) -> list:
    """
    Returns list of fully-formed bet dicts ready to add to bets_data['active'],
    plus metadata for the Telegram alert.
    existing_team_pairs: set of (home_lower, away_lower) for already-covered games.
    next_bet_id: starting ID for new bets.
    """
    upcoming = _get_upcoming_games(days=3)
    opportunities = []
    bet_id = next_bet_id

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
        suggestion = _suggest_bet(game, news)
        stake = TIER_STAKES[suggestion["tier"]]

        bet = {
            "id": bet_id,
            "description": f"{suggestion['selection']} {suggestion['bet_type'].replace('_', ' ')} vs "
                           f"{game['away'] if suggestion['selection'] == game['home'] else game['home']}",
            "bet_type": suggestion["bet_type"],
            "selection": suggestion["selection"],
            "odds": suggestion["estimated_odds"],
            "stake": stake,
            "kickoff": ko_str,
            "espn_game_id": game["game_id"],
            "home": game["home"],
            "away": game["away"],
            "tier": suggestion["tier"],
            "estimated_prob": suggestion["estimated_prob"],
            "notes": _build_notes(game, news, suggestion, hours_out),
        }
        if suggestion.get("line"):
            bet["line"] = suggestion["line"]

        opportunities.append({
            "bet": bet,
            "game": game,
            "hours_out": hours_out,
            "news": news[:3],
            "suggestion": suggestion,
            "stake": stake,
        })
        bet_id += 1

    return opportunities
