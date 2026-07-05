import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from monitor.news import get_injury_news
from monitor.scores import get_live_score, discover_game_id
from notify.telegram import TelegramNotifier
from utils.pnl import calculate_result
from utils.state import load_state, save_state

BASE = Path(__file__).parent
BETS_FILE = BASE / "data" / "bets.json"
STATE_FILE = BASE / "data" / "state.json"

# Minutes between notifications per phase
NOTIFY_INTERVAL_LIVE = 4       # during game: every ~5 min (matches Actions cadence)
NOTIFY_INTERVAL_CLOSE = 18     # within 2 hours of KO: every 20 min
NOTIFY_INTERVAL_PREGAME = 55   # more than 2 hours out: hourly


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


def should_notify(bet_id: str, state: dict, mins_to_ko: float) -> bool:
    last_str = state.get("last_notified", {}).get(bet_id)
    if not last_str:
        return True
    last = datetime.fromisoformat(last_str)
    mins_since = (datetime.now(timezone.utc) - last).total_seconds() / 60

    if mins_to_ko <= 0:
        return mins_since >= NOTIFY_INTERVAL_LIVE
    if mins_to_ko <= 120:
        return mins_since >= NOTIFY_INTERVAL_CLOSE
    return mins_since >= NOTIFY_INTERVAL_PREGAME


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("ERROR: Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID", file=sys.stderr)
        sys.exit(1)

    notifier = TelegramNotifier(token, chat_id)
    bets_data = load_bets()
    state = load_state(STATE_FILE)

    if not bets_data["active"]:
        print("No active bets. Skipping.")
        return

    for bet in list(bets_data["active"]):
        bet_id = str(bet["id"])
        mins = mins_to_kickoff(bet["kickoff"])

        # Discover ESPN game ID if missing
        if not bet.get("espn_game_id"):
            gid = discover_game_id(bet["home"], bet["away"])
            if gid:
                bet["espn_game_id"] = gid

        score = get_live_score(bet.get("espn_game_id"), bet["home"], bet["away"])

        # Goal alerts (compare with last known state)
        prev_score = state.get("last_scores", {}).get(bet_id)
        if score and prev_score:
            for goal in detect_new_goals(prev_score, score):
                notifier.send_goal_alert(bet, score, goal)

        if score:
            state.setdefault("last_scores", {})[bet_id] = score

        # Settle completed game
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

        # Regular status update
        if should_notify(bet_id, state, mins):
            news = get_injury_news(bet["home"], bet["away"]) if mins > 0 else []
            notifier.send_status_update(bet, score, news, mins, bets_data["bankroll"])
            state.setdefault("last_notified", {})[bet_id] = (
                datetime.now(timezone.utc).isoformat()
            )

    # Daily P&L summary (once per day around 09:00 UTC)
    now_hour = datetime.now(timezone.utc).hour
    now_min = datetime.now(timezone.utc).minute
    last_summary = state.get("last_pnl_summary", "")
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if now_hour == 9 and now_min < 10 and last_summary != today_str:
        notifier.send_pnl_summary(bets_data)
        state["last_pnl_summary"] = today_str

    save_state(STATE_FILE, state)
    save_bets(bets_data)
    print(f"Done. Active bets: {len(bets_data['active'])} | Balance: ${bets_data['bankroll']['current']:.2f}")


if __name__ == "__main__":
    main()
