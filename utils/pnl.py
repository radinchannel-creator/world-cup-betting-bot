from typing import Optional


TEAM_ALIASES: dict[str, list[str]] = {
    "brazil": ["brazil", "brasil"],
    "norway": ["norway"],
    "mexico": ["mexico"],
    "england": ["england"],
    "spain": ["spain"],
    "portugal": ["portugal"],
    "usa": ["usa", "united states", "us", "usmnt"],
    "belgium": ["belgium"],
    "morocco": ["morocco"],
    "canada": ["canada"],
    "france": ["france"],
    "paraguay": ["paraguay"],
}


def calculate_result(bet: dict, score: dict) -> dict:
    bet_type = bet.get("bet_type", "ml")
    stake = float(bet["stake"])
    odds = float(bet["odds"])
    win_pnl = round(stake * (odds - 1), 2)

    home_score = score.get("home_score", 0)
    away_score = score.get("away_score", 0)
    total_goals = home_score + away_score

    selection = bet.get("selection", "").lower()
    home_team = score.get("home_team", "").lower()
    away_team = score.get("away_team", "").lower()

    selected_is_home = _team_matches(selection, home_team)
    selected_score = home_score if selected_is_home else away_score
    other_score = away_score if selected_is_home else home_score

    if bet_type == "ml":
        if selected_score > other_score:
            return {"outcome": "WIN", "pnl": win_pnl}
        return {"outcome": "LOSS", "pnl": -stake}

    if bet_type == "dnb":
        if selected_score > other_score:
            return {"outcome": "WIN", "pnl": win_pnl}
        if selected_score == other_score:
            return {"outcome": "VOID", "pnl": 0.0}
        return {"outcome": "LOSS", "pnl": -stake}

    if bet_type == "over_goals":
        line = float(bet.get("line", 2.5))
        if total_goals > line:
            return {"outcome": "WIN", "pnl": win_pnl}
        if score.get("state") != "post" and total_goals <= line:
            return {"outcome": "WINNING" if total_goals > line else "LOSING", "pnl": 0.0}
        return {"outcome": "LOSS", "pnl": -stake}

    if bet_type == "under_goals":
        line = float(bet.get("line", 2.5))
        if score.get("state") == "post":
            if total_goals < line:
                return {"outcome": "WIN", "pnl": win_pnl}
            return {"outcome": "LOSS", "pnl": -stake}
        return {
            "outcome": "WINNING" if total_goals < line else "LOSING",
            "pnl": 0.0,
        }

    if bet_type == "anytime_scorer":
        goals = score.get("goals", [])
        scored = any(
            selection in " ".join(g.get("scorers", [])).lower()
            for g in goals
        )
        if scored:
            return {"outcome": "WIN", "pnl": win_pnl}
        if score.get("state") == "post":
            return {"outcome": "LOSS", "pnl": -stake}
        return {"outcome": "PENDING", "pnl": 0.0}

    return {"outcome": "UNKNOWN", "pnl": 0.0}


def ev_percentage(estimated_prob: float, odds: float) -> float:
    implied_prob = 1 / odds
    return round((estimated_prob - implied_prob) * 100, 1)


def _team_matches(selection: str, team_name: str) -> bool:
    for canonical, aliases in TEAM_ALIASES.items():
        if selection in aliases and team_name in aliases:
            return True
    return selection in team_name or team_name in selection
