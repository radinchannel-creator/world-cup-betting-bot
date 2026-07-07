import requests
from datetime import datetime, timezone
from typing import Optional

from utils.pnl import calculate_result, ev_percentage


class TelegramNotifier:
    API_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def send(self, text: str):
        url = self.API_URL.format(token=self.token)
        try:
            r = requests.post(
                url,
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            r.raise_for_status()
        except Exception as e:
            print(f"Telegram send failed: {e}")

    def send_status_update(
        self,
        bet: dict,
        score: Optional[dict],
        news: list,
        mins_to_ko: float,
        bankroll: dict,
    ):
        tier_emoji = {"S": "🔥", "A": "💪", "B": "✅", "C": "🎯"}.get(
            bet.get("tier", "B"), "✅"
        )
        potential = round(bet["stake"] * (bet["odds"] - 1), 2)
        ev = ev_percentage(
            bet.get("estimated_prob", 0.5), bet["odds"]
        )
        ev_str = f"+{ev}%" if ev >= 0 else f"{ev}%"

        if mins_to_ko > 120:
            timing = f"⏰ {int(mins_to_ko // 60)}h {int(mins_to_ko % 60)}m to KO — <i>hourly check</i>"
        elif mins_to_ko > 20:
            timing = f"⏰ {int(mins_to_ko)}m to KO — <i>20-min check</i>"
        elif mins_to_ko > 0:
            timing = f"🚨 {int(mins_to_ko)}m to KO — <b>CHECK LINEUP NOW</b>"
        else:
            timing = "🔴 <b>LIVE</b>"

        lines = [
            f"{tier_emoji} <b>BET #{bet['id']} — {bet['description'].upper()}</b>",
            "",
            f"🆚 {bet['home']} vs {bet['away']}",
            f"💰 ${bet['stake']} @ {bet['odds']} → +${potential} | Edge: <b>{ev_str}</b>",
            timing,
        ]

        if score and score["state"] == "in":
            lines += [
                "",
                f"⚽ <b>LIVE:</b> {score['home_team']} {score['home_score']}–"
                f"{score['away_score']} {score['away_team']} ({score['clock']})",
            ]
            outcome = self._current_outcome_str(bet, score)
            lines.append(f"→ Your bet: {outcome}")

        if news:
            lines += ["", "📰 <b>Latest intel:</b>"]
            for item in news[:2]:
                src = f" ({item['source']})" if item.get("source") else ""
                lines.append(f"• {item['title']}{src}")

        if bet.get("notes"):
            lines += ["", f"💡 <i>{bet['notes']}</i>"]

        lines += [
            "",
            f"💼 Balance: <b>${bankroll['current']:.2f}</b> ({self._roi(bankroll)}% ROI)",
        ]

        self.send("\n".join(lines))

    def send_goal_alert(self, bet: dict, score: dict, goal: dict):
        scorers_str = ", ".join(goal["scorers"]) if goal["scorers"] else "Unknown"
        outcome = self._current_outcome_str(bet, score)

        lines = [
            f"⚽ <b>GOAL!</b> {score['home_team']} {score['home_score']}–"
            f"{score['away_score']} {score['away_team']} ({goal['time']}′)",
            f"Scorer: <b>{scorers_str}</b> for {goal['team']}",
            "",
            f"Bet #{bet['id']}: {outcome}",
        ]
        self.send("\n".join(lines))

    def send_settlement(self, bet: dict, bankroll: dict):
        outcome = bet.get("outcome", "UNKNOWN")
        pnl = float(bet.get("pnl", 0))
        emoji = {"WIN": "🏆", "LOSS": "❌", "VOID": "↩️"}.get(outcome, "❓")

        if pnl > 0:
            pnl_str = f"<b>+${pnl:.2f}</b>"
        elif pnl == 0:
            pnl_str = "$0.00 (stake returned)"
        else:
            pnl_str = f"<b>-${abs(pnl):.2f}</b>"

        profit_total = bankroll["current"] - bankroll["start"]
        profit_str = f"+${profit_total:.2f}" if profit_total >= 0 else f"-${abs(profit_total):.2f}"

        lines = [
            f"{emoji} <b>BET #{bet['id']} SETTLED — {outcome}</b>",
            "",
            f"{bet['description']}",
            f"Odds: {bet['odds']} | Stake: ${bet['stake']:.2f} | P&L: {pnl_str}",
            "",
            f"💼 <b>Balance: ${bankroll['current']:.2f}</b>",
            f"📈 Total profit: {profit_str} ({self._roi(bankroll)}% ROI from ${bankroll['start']:.2f})",
        ]
        self.send("\n".join(lines))

    def send_pnl_summary(self, bets_data: dict):
        bankroll = bets_data["bankroll"]
        settled = bets_data.get("settled", [])
        active = bets_data.get("active", [])

        wins = [b for b in settled if b.get("outcome") == "WIN"]
        losses = [b for b in settled if b.get("outcome") == "LOSS"]
        voids = [b for b in settled if b.get("outcome") == "VOID"]

        win_profit = sum(float(b.get("pnl", 0)) for b in wins)
        loss_total = sum(abs(float(b.get("pnl", 0))) for b in losses)
        active_exposure = sum(float(b["stake"]) for b in active)

        lines = [
            "📊 <b>P&L SUMMARY</b>",
            f"<i>{datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}</i>",
            "",
            f"✅ Won:  {len(wins)} bets | +${win_profit:.2f}",
            f"❌ Lost: {len(losses)} bets | -${loss_total:.2f}",
            f"↩️ Void: {len(voids)} bets",
            "",
            f"💼 <b>Balance: ${bankroll['current']:.2f}</b>",
            f"📈 <b>ROI: {self._roi(bankroll)}%</b> from ${bankroll['start']:.2f} start",
            f"🎯 Win rate: {self._win_rate(wins, losses)}",
            "",
        ]

        if active:
            lines.append(f"<b>Active bets ({len(active)}, ${active_exposure:.2f} at risk):</b>")
            for b in active:
                potential = round(float(b["stake"]) * (float(b["odds"]) - 1), 2)
                lines.append(
                    f"• #{b['id']} {b['description']} @ {b['odds']} "
                    f"(${b['stake']} → +${potential})"
                )
        else:
            lines.append("No active bets.")

        self.send("\n".join(lines))

    def send_injury_alert(self, bet: dict, news: list, mins_to_ko: float):
        if mins_to_ko > 0:
            timing = f"⏰ {int(mins_to_ko // 60)}h {int(mins_to_ko % 60)}m to KO"
        else:
            timing = "🔴 LIVE"

        lines = [
            f"🚨 <b>NEWS ALERT — Bet #{bet['id']}</b>",
            f"⚽ {bet['home']} vs {bet['away']} | {timing}",
            "",
            "📰 <b>Breaking:</b>",
        ]
        for item in news[:3]:
            src = f" ({item['source']})" if item.get("source") else ""
            lines.append(f"• {item['title']}{src}")

        lines += ["", f"💡 Check if this affects your {bet['description']} bet"]
        self.send("\n".join(lines))

    def send_opportunity_alert(self, opp: dict):
        game = opp["game"]
        hours = opp["hours_out"]
        news = opp.get("news", [])
        bet = opp["bet"]
        suggestion = opp.get("suggestion", {})

        h_str = f"{hours:.0f}h" if hours >= 1 else f"{hours * 60:.0f}m"
        tier_emoji = {"S": "🔥", "A": "💪", "B": "✅", "C": "🎯"}.get(bet.get("tier", "B"), "✅")
        potential = round(bet["stake"] * (bet["odds"] - 1), 2)

        lines = [
            f"🔍 <b>NEW BET AUTO-ADDED — #{bet['id']}</b>",
            f"",
            f"⚽ <b>{game['name']}</b>",
            f"⏰ Kicks off in {h_str}",
            f"",
            f"{tier_emoji} {bet['bet_type'].upper().replace('_',' ')} — <b>{bet['selection']}</b>",
            f"💰 ${bet['stake']} @ est. {bet['odds']} → +${potential} potential",
            f"",
            f"⚠️ <i>Odds are estimated — verify on Leon Bet before placing.</i>",
            f"➡️ Place this bet now, tracking starts immediately.",
        ]

        if news:
            lines += ["", "📰 <b>Intel:</b>"]
            for item in news[:2]:
                src = f" ({item['source']})" if item.get("source") else ""
                lines.append(f"• {item['title']}{src}")

        self.send("\n".join(lines))

    def _current_outcome_str(self, bet: dict, score: dict) -> str:
        result = calculate_result(bet, score)
        outcome = result.get("outcome", "UNKNOWN")
        return {
            "WIN": "✅ WINNING",
            "WINNING": "✅ WINNING",
            "LOSS": "❌ LOSING",
            "LOSING": "❌ LOSING",
            "VOID": "↩️ VOID (draw — stake safe)",
            "PENDING": "⏳ PENDING",
        }.get(outcome, "⏳ PENDING")

    def _roi(self, bankroll: dict) -> str:
        roi = ((bankroll["current"] - bankroll["start"]) / bankroll["start"]) * 100
        return f"{roi:+.1f}"

    def _win_rate(self, wins: list, losses: list) -> str:
        total = len(wins) + len(losses)
        if total == 0:
            return "N/A"
        return f"{len(wins)}/{total} ({len(wins) / total * 100:.0f}%)"
