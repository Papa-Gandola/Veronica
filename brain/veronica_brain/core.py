"""Ядро brain: один «тик» надзора, вечерний отчёт, команды."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .config import STRATEGIES, Settings
from .ft_client import FreqtradeClient, FreqtradeError
from .journal import Journal
from .notify import Notifier
from .reports import HELP_TEXT, daily_report_text, status_text, trade_closed_text
from .review import Reviewer
from .risk import RiskManager
from .stats import summarize, window
from .strategy_manager import StrategyManager

log = logging.getLogger("veronica.core")


class Brain:
    def __init__(self, settings: Settings, journal: Journal, ft: FreqtradeClient, notifier: Notifier):
        self.s = settings
        self.j = journal
        self.ft = ft
        self.notify = notifier
        self.risk = RiskManager(settings, journal)
        self.strategies = StrategyManager(settings, journal, ft)
        self.reviewer = Reviewer(settings, journal)
        if not self.j.get("brain_started_at"):
            self.j.set("brain_started_at", datetime.now(timezone.utc).isoformat())

    # --- снимок -------------------------------------------------------------
    def snapshot(self) -> dict:
        bal = self.ft.balance()
        profit = self.ft.profit()
        open_trades = self.ft.status()
        cfg = self.ft.show_config()
        # total — весь кошелёк в USDT (вкл. открытые позиции). На торговом счёте
        # OKX должны лежать только деньги Veronica, иначе просадка считается неверно.
        equity = float(bal.get("total") or bal.get("total_bot") or 0.0)
        strategy = str(cfg.get("strategy") or self.strategies.active())
        state = str(cfg.get("state") or "?")
        self.j.add_snapshot(
            equity=equity,
            profit_closed=float(profit.get("profit_closed_coin") or 0.0),
            profit_all=float(profit.get("profit_all_coin") or 0.0),
            open_trades=len(open_trades),
            strategy=strategy,
            bot_state=state,
        )
        return {"equity": equity, "strategy": strategy, "state": state, "open": open_trades, "profit": profit}

    # --- синк сделок --------------------------------------------------------
    def sync_trades(self, announce: bool = True) -> int:
        new = 0
        data = self.ft.trades(limit=50)
        for t in data.get("trades", []):
            if self.j.upsert_trade(t):
                new += 1
                if announce and self.j.get("trades_synced_once") == "1":
                    # дублирует уведомление freqtrade в Telegram, но нужно для GandolaChat
                    if self.notify.gandola:
                        try:
                            self.notify.gandola.send(trade_closed_text(t))
                        except Exception as e:  # noqa: BLE001
                            log.warning("gandola trade notify failed: %s", e)
        self.j.set("trades_synced_once", "1")
        return new

    # --- тик ----------------------------------------------------------------
    def tick(self) -> None:
        if not self.ft.ping():
            log.warning("freqtrade недоступен")
            return
        snap = self.snapshot()
        self.sync_trades()

        # если остановлены по риску — следим, чтобы кто-то не включил бота мимо нас
        if self.risk.is_halted():
            if snap["state"] == "running":
                self.ft.stop()
                self.notify.send("⛔ Veronica остановлена по риску. Бот был запущен вручную — останавливаю снова. "
                                 "Чтобы продолжить: /resume")
            return

        decision = self.risk.evaluate(snap["equity"])
        if decision.action == "halt":
            self.ft.stop()
            self.risk.set_halted(True)
            self.j.add_event("halt", decision.reason)
            self.notify.send(
                f"⛔ СТОП ПО ПРОСАДКЕ\n{decision.reason}\n"
                f"Торговля остановлена, открытые ордера отменены. Жду /resume."
            )
        elif decision.action == "pause_day":
            self.ft.pause()
            self.risk.set_paused_today()
            self.j.add_event("daily_loss", decision.reason)
            self.notify.send(f"⏸ Дневной лимит убытка\n{decision.reason}\nНовых входов до завтра (UTC) не будет.")
        elif self.risk.paused_today() and snap["state"] == "paused":
            # новый день — снимаем вчерашнюю паузу
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self.j.get("paused_day") != today:
                self.ft.start()
                self.notify.send("▶️ Новый день — пауза по дневному лимиту снята.")

    # --- вечерний отчёт -----------------------------------------------------
    def daily_review(self, force: bool = False) -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not force and self.j.get("last_report_day") == today:
            return ""
        snap = self.snapshot()
        self.sync_trades(announce=False)
        strategy = snap["strategy"]

        rule = self.reviewer.rule_verdict(strategy)
        context = self.reviewer.build_context(strategy, snap["equity"], snap["state"], rule)
        claude = self.reviewer.claude_review(context)

        switched: str | None = None
        target: str | None = None
        if rule.verdict == "switch" and rule.recommended:
            if claude is None:
                target = rule.recommended
            elif claude.get("verdict") == "switch" and float(claude.get("confidence", 0)) >= 0.7:
                target = claude.get("recommended_strategy") or rule.recommended
        if target and target in STRATEGIES:
            if self.strategies.days_since_switch() < self.s.switch_cooldown_days:
                rule.reasons.append(
                    f"смена стратегии отложена: прошло меньше {self.s.switch_cooldown_days} дней с прошлой"
                )
            elif self.risk.is_halted():
                rule.reasons.append("стратегия не меняется, пока торговля остановлена по риску")
            else:
                self.reviewer.mark_failed(strategy)
                try:
                    switched = self.strategies.switch(target, "деградация по правилам" + (" и мнению Claude" if claude else ""))
                except (FreqtradeError, ValueError) as e:
                    rule.reasons.append(f"смена не удалась: {e}")

        verdict = (claude or {}).get("verdict") or rule.verdict
        self.j.add_review(
            strategy=strategy,
            verdict=verdict,
            recommended=(claude or {}).get("recommended_strategy") or rule.recommended,
            confidence=(claude or {}).get("confidence"),
            summary=(claude or {}).get("summary_ru") or "; ".join(rule.reasons) or "без замечаний",
            applied=bool(switched),
            raw={"rule": {"verdict": rule.verdict, "reasons": rule.reasons, "stats": rule.stats}, "claude": claude},
        )
        text = daily_report_text(
            self.s, snap["equity"], self.strategies.active(),
            summarize(self.j.trades_since(window(1))), summarize(self.j.trades_since(window(7))),
            rule.reasons, claude, switched,
        )
        self.j.set("last_report_day", today)
        self.notify.send(text)
        return text

    def report_due(self) -> bool:
        now = datetime.now(timezone.utc)
        return now.hour == self.s.report_hour_utc and self.j.get("last_report_day") != now.strftime("%Y-%m-%d")

    # --- команды ------------------------------------------------------------
    def command(self, text: str, who: str = "cli") -> str | None:
        """Обрабатывает команду; возвращает ответ или None, если это не команда."""
        raw = text.strip()
        low = raw.lower()
        # в чате реагируем на /команды и на обращение «вероника, …»
        if low.startswith(("вероника", "veronica")):
            raw = raw.split(maxsplit=1)[1] if " " in raw else ""
            low = raw.lower()
            if not low.startswith("/"):
                low = "/" + low
                raw = "/" + raw
        if not low.startswith("/"):
            return None
        parts = raw.split()
        cmd = parts[0].lower().lstrip("/")
        arg = parts[1] if len(parts) > 1 else ""
        log.info("command %s from %s", raw, who)
        try:
            if cmd in ("status", "статус", "s"):
                snap = self.snapshot()
                return status_text(self.s, snap["equity"], snap["strategy"], snap["state"], snap["open"],
                                   snap["profit"], self.risk.evaluate(snap["equity"]).drawdown, self.risk.is_halted())
            if cmd in ("report", "отчёт", "отчет"):
                return self.daily_review(force=True)
            if cmd in ("pause", "пауза"):
                self.ft.pause()
                self.j.add_event("pause", f"по команде {who}")
                return "⏸ Пауза: новых сделок не открываю, открытые доводятся."
            if cmd in ("halt", "stop", "стоп"):
                self.ft.stop()
                self.risk.set_halted(True)
                self.j.add_event("halt", f"по команде {who}")
                return "⛔ Торговля остановлена до /resume."
            if cmd in ("resume", "start", "продолжай", "старт"):
                snap = self.snapshot()
                self.risk.set_halted(False)
                self.risk.reset_baseline(snap["equity"])
                self.j.set("paused_day", "")
                self.ft.start()
                self.j.add_event("resume", f"по команде {who}; база просадки = {snap['equity']:.2f}")
                return f"▶️ Продолжаю. База для стопа по просадке теперь {snap['equity']:.2f} USDT."
            if cmd in ("strategy", "стратегия"):
                if not arg:
                    return f"Активная стратегия: {self.strategies.active()}"
                return self.strategies.switch(arg, f"по команде {who}")
            if cmd in ("strategies", "стратегии"):
                return "\n".join(f"• {k} — {v}" for k, v in STRATEGIES.items())
            if cmd in ("help", "помощь"):
                return HELP_TEXT
        except FreqtradeError as e:
            return f"Ошибка freqtrade: {e}"
        except ValueError as e:
            return f"Ошибка: {e}"
        return None
