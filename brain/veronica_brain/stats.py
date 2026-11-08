"""Сводная статистика по сделкам из дневника (без зависимости от pandas)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def summarize(trades: list[dict]) -> dict:
    """Winrate, profit factor, матожидание, просадка по закрытым сделкам."""
    if not trades:
        return {"trades": 0}
    profits = [t["profit_abs"] or 0.0 for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [-p for p in profits if p < 0]
    gross_win = sum(wins)
    gross_loss = sum(losses)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in profits:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    durations = [t["duration_min"] for t in trades if t.get("duration_min")]
    by_pair: dict[str, float] = defaultdict(float)
    by_reason: dict[str, int] = defaultdict(int)
    for t in trades:
        by_pair[t["pair"]] += t["profit_abs"] or 0.0
        by_reason[t.get("exit_reason") or "?"] += 1
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "winrate": round(len(wins) / len(trades), 3),
        "profit_abs": round(sum(profits), 4),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0),
        "expectancy": round(sum(profits) / len(trades), 4),
        "avg_win": round(gross_win / len(wins), 4) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 4) if losses else 0.0,
        "max_drawdown_abs": round(max_dd, 4),
        "avg_duration_h": round(sum(durations) / len(durations) / 60, 1) if durations else None,
        "by_pair": {k: round(v, 4) for k, v in sorted(by_pair.items(), key=lambda kv: -kv[1])},
        "exit_reasons": dict(by_reason),
    }


def window(days: int) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(days=days))
