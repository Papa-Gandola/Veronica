"""
Риск-надзор. Два правила, которые brain применяет поверх freqtrade:

1. Стоп по просадке: капитал упал ниже (1 - MAX_DRAWDOWN) от базы →
   freqtrade останавливается (stop), ставится флаг halted. Снимает флаг
   только человек командой resume. При resume база пересчитывается от
   текущего капитала.
2. Дневной лимит: убыток за текущий день UTC больше MAX_DAILY_LOSS от
   капитала на начало дня → pause (новых входов нет, открытые закрываются
   по правилам стратегии) до следующего дня.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Settings
from .journal import Journal

log = logging.getLogger("veronica.risk")


@dataclass
class RiskDecision:
    action: str | None = None   # "halt" | "pause_day" | None
    reason: str = ""
    drawdown: float = 0.0
    daily_pnl_ratio: float = 0.0


class RiskManager:
    def __init__(self, settings: Settings, journal: Journal):
        self.s = settings
        self.j = journal

    # --- база для просадки --------------------------------------------------
    def baseline(self) -> float:
        raw = self.j.get("dd_baseline")
        if raw is None:
            self.j.set("dd_baseline", str(self.s.initial_capital))
            return self.s.initial_capital
        return float(raw)

    def reset_baseline(self, equity: float) -> None:
        self.j.set("dd_baseline", str(equity))

    def is_halted(self) -> bool:
        return self.j.get("halted", "0") == "1"

    def set_halted(self, value: bool) -> None:
        self.j.set("halted", "1" if value else "0")

    # --- дневной лимит ------------------------------------------------------
    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def day_start_equity(self, equity: float) -> float:
        rec = self.j.get_json("day_start") or {}
        if rec.get("day") != self._today():
            rec = {"day": self._today(), "equity": equity}
            self.j.set_json("day_start", rec)
        return float(rec["equity"])

    def paused_today(self) -> bool:
        return self.j.get("paused_day") == self._today()

    def set_paused_today(self) -> None:
        self.j.set("paused_day", self._today())

    # --- решение ------------------------------------------------------------
    def evaluate(self, equity: float) -> RiskDecision:
        base = self.baseline()
        dd = (base - equity) / base if base > 0 else 0.0
        day_eq = self.day_start_equity(equity)
        daily = (equity - day_eq) / day_eq if day_eq > 0 else 0.0
        d = RiskDecision(drawdown=round(dd, 4), daily_pnl_ratio=round(daily, 4))

        if dd >= self.s.max_drawdown:
            d.action = "halt"
            d.reason = (
                f"Просадка {dd:.1%} от базы {base:.2f} USDT (капитал {equity:.2f}) "
                f"≥ лимита {self.s.max_drawdown:.0%}"
            )
            return d
        if daily <= -self.s.max_daily_loss and not self.paused_today():
            d.action = "pause_day"
            d.reason = (
                f"Убыток за день {daily:.1%} (с {day_eq:.2f} до {equity:.2f} USDT) "
                f"≥ дневного лимита {self.s.max_daily_loss:.0%}"
            )
        return d
