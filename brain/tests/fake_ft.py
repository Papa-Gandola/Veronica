"""Заглушка freqtrade API для тестов brain."""

from __future__ import annotations


class FakeFT:
    def __init__(self, equity: float = 100.0, strategy: str = "VeronicaTrend"):
        self.equity = equity
        self.state = "running"
        self.strategy_name = strategy
        self.closed: list[dict] = []
        self.open: list[dict] = []
        self.calls: list[str] = []

    def ping(self):
        return True

    def show_config(self):
        return {"state": self.state, "strategy": self.strategy_name, "dry_run": True}

    def balance(self):
        return {"total_bot": self.equity, "total": self.equity}

    def profit(self):
        return {"profit_closed_coin": sum(t["profit_abs"] for t in self.closed), "profit_all_coin": 0.0,
                "closed_trade_count": len(self.closed), "winrate": 0.5, "profit_factor": 1.0}

    def status(self):
        return self.open

    def trades(self, limit=50, offset=0):
        return {"trades": list(reversed(self.closed))[:limit], "trades_count": len(self.closed)}

    def start(self):
        self.calls.append("start"); self.state = "running"; return {"status": "ok"}

    def stop(self):
        self.calls.append("stop"); self.state = "stopped"; return {"status": "ok"}

    def pause(self):
        self.calls.append("pause"); self.state = "paused"; return {"status": "ok"}

    def reload_config(self):
        self.calls.append("reload_config"); return {"status": "ok"}


def make_trade(i: int, profit_abs: float, strategy: str = "VeronicaTrend", close_date: str = "2026-01-10T10:00:00+00:00",
               pair: str = "BTC/USDT") -> dict:
    return {
        "trade_id": i, "pair": pair, "strategy": strategy, "enter_tag": "trend_pullback",
        "exit_reason": "roi" if profit_abs > 0 else "stop_loss",
        "open_date": "2026-01-10T00:00:00+00:00", "close_date": close_date,
        "open_rate": 100.0, "close_rate": 100.0 + profit_abs, "stake_amount": 33.0,
        "profit_abs": profit_abs, "profit_ratio": profit_abs / 33.0, "trade_duration": 600,
    }
