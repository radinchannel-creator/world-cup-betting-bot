import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from monitor.news import get_injury_news
from monitor.opportunities import find_opportunities
from monitor.scores import get_live_score, discover_game_id
from notify.telegram import TelegramNotifier
from utils.pnl import calculate_result
from utils.state import load_state, save_state

BASE = Path(__file__).parent
BETS_FILE = BASE / "data" / "bets.json"
STATE_FILE = BASE / "data" / "state.json"

OPPORTUNITY_SCAN_INTERVAL_MINS = 55


def load_bets() -> dict:
    with open(BETS_FILE) as f:
        return json.load(f)


def save_bets(data: dict):
    with open(BETS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def mins_to_kickoff(kickoff_str: str) -> float:
    ko = datetime.fromisoformat(kickoff_str)
    if ko.tzinfo is None:
        ko = ko.replace(tzinfo=timezone.utc)
    return (ko - datetime.now(timezone.utc)).total_seconds() / 60


def detect_new_goals(prev: dict, curr: dict) -> list:
    prev_goals = prev.get("goals", [])
    curr_goals = curr.get("goals", [])
    return curr_goals[len(prev_goals):] if len(curr_goals) > len(prev_goals) else []


def news_hash(news_items: list) -> str:
    titles = "|".join(sorted(n.get("title", "") for n in news_items))
    return hashlib.md5(titles.encode()).hexdigest()


def should_scan_opportunities(state: dict) -> bool:
    last = state.get("last_opportunity_scan")
    if not last:
        return True
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 60
    return elapsed >= OPPORTUNITY_SCAN_INTERVAL_MINS


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("ERROR: Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID", file=sys.stderr)
        sys.exit(1)

    notifier = TelegramNotifier(token, chat_id)
    bets_data = load_bets()
    state = load_state(STATE_FILE)

    # ── Monitor active bets ───────────────────────────────────────────────────
    for bet in list(bets_data["active"]):
        bet_id = str(bet["id"])
        mins = mins_to_kickoff(bet["kickoff"])

        # Auto-discover ESPN game ID if missing
        if not bet.get("espn_game_id"):
            gid = discover_game_id(bet["home"], bet["away"])
            if gid:
                bet["espn_game_id"] = gid

        score = get_live_score(bet.get("espn_game_id"), bet["home"], bet["away"])

        # Goal alerts — always instant
        prev_score = state.get("last_scores", {}).get(bet_id)
        if score and prev_score:
            for goal in detect_new_goals(prev_score, score):
                notifier.send_goal_alert(bet, score, goal)

        if score:
            state.setdefault("last_scores", {})[bet_id] = score

        # Auto-settle completed games
        if score and score.get("state") == "post":
            result = calculate_result(bet, score)
            bets_data["bankroll"]["current"] = round(
                bets_data["bankroll"]["current"] + result["pnl"], 2
            )
            settled = {
                **bet,
                "settled_at": datetime.now(timezone.utc).isoformat(),
                **result,
            }
            bets_data["settled"].append(settled)
            bets_data["active"].remove(bet)
            notifier.send_settlement(settled, bets_data["bankroll"])
            continue

        # Injury/news alert — only notify when news actually changes
        if mins > -90:
            news = get_injury_news(bet["home"], bet["away"])
            h = news_hash(news)
            prev_hash = state.get("last_news_hashes", {}).get(bet_id)
            if news and h != prev_hash:
                notifier.send_injury_alert(bet, news, mins)
                state.setdefault("last_news_hashes", {})[bet_id] = h

    # ── Opportunity scanner ───────────────────────────────────────────────────
    if should_scan_opportunities(state):
        existing_pairs = {
            (b["home"].lower(), b["away"].lower())
            for b in bets_data["active"]
        }
        notified = set(state.get("notified_opportunities", []))

        for opp in find_opportunities(existing_pairs):
            gid = opp["game"]["game_id"]
            if gid not in notified:
                notifier.send_opportunity_alert(opp)
                notified.add(gid)

        state["notified_opportunities"] = list(notified)
        state["last_opportunity_scan"] = datetime.now(timezone.utc).isoformat()

    # ── Daily P&L summary at 09:00 UTC ────────────────────────────────────────
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    if now.hour == 9 and now.minute < 10 and state.get("last_pnl_summary") != today_str:
        notifier.send_pnl_summary(bets_data)
        state["last_pnl_summary"] = today_str

    save_state(STATE_FILE, state)
    save_bets(bets_data)
    print(
        f"Done. Active: {len(bets_data['active'])} | "
        f"Balance: ${bets_data['bankroll']['current']:.2f}"
    )


if __name__ == "__main__":
    main()
