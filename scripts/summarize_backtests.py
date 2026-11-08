#!/usr/bin/env python3
"""
Собирает из последних результатов бэктеста (user_data/backtest_results/*.zip|*.json)
краткий эталон по стратегиям → user_data/backtest_results/summary.json.
Его читает brain, чтобы сравнивать живую торговлю с ожиданиями.
Зависимостей нет — только стандартная библиотека.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "user_data" / "backtest_results"


def load_results() -> dict[str, dict]:
    """Последний результат для каждой стратегии (по времени файла)."""
    out: dict[str, tuple[float, dict]] = {}
    for f in RESULTS.iterdir():
        if f.name.startswith(".") or f.name == "summary.json" or f.name.endswith(".meta.json"):
            continue
        try:
            if f.suffix == ".zip":
                with zipfile.ZipFile(f) as z:
                    name = next(n for n in z.namelist() if n.endswith(".json") and not n.endswith(".meta.json")
                                and "_config" not in n and "_signals" not in n and "_exited" not in n
                                and "_rejected" not in n and "_market_change" not in n)
                    data = json.loads(z.read(name))
            elif f.suffix == ".json" and f.name != "last_result.json":
                data = json.loads(f.read_text())
            else:
                continue
        except (OSError, json.JSONDecodeError, StopIteration, zipfile.BadZipFile):
            continue
        for strat, res in data.get("strategy", {}).items():
            mtime = f.stat().st_mtime
            if strat not in out or out[strat][0] < mtime:
                out[strat] = (mtime, res)
    return {k: v[1] for k, v in out.items()}


def summarize(res: dict) -> dict:
    trades = res.get("total_trades", 0)
    wins = res.get("wins", 0)
    return {
        "timerange": f"{res.get('backtest_start', '?')[:10]} — {res.get('backtest_end', '?')[:10]}",
        "trades": trades,
        "trades_per_day": round(res.get("trades_per_day", 0), 2),
        "winrate": round(wins / trades, 3) if trades else 0.0,
        "profit_factor": round(res.get("profit_factor", 0.0), 3),
        "profit_total_pct": round(res.get("profit_total", 0.0) * 100, 2),
        "profit_total_abs": round(res.get("profit_total_abs", 0.0), 2),
        "max_drawdown_account_pct": round(res.get("max_drawdown_account", 0.0) * 100, 2),
        "cagr_pct": round(res.get("cagr", 0.0) * 100, 2),
        "sharpe": round(res.get("sharpe", 0.0), 2),
        "expectancy": round(res.get("expectancy", 0.0), 4),
        "avg_duration": res.get("holding_avg_s", 0) and f"{res['holding_avg_s'] / 3600:.1f}h",
        "market_change_pct": round(res.get("market_change", 0.0) * 100, 2),
        "starting_balance": res.get("starting_balance"),
    }


def main() -> int:
    results = load_results()
    if not results:
        print("нет результатов бэктеста в", RESULTS, file=sys.stderr)
        return 1
    summary = {k: summarize(v) for k, v in sorted(results.items())}
    (RESULTS / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"{'стратегия':<18}{'сделок':>8}{'winrate':>9}{'PF':>7}{'прибыль%':>10}{'просадка%':>11}{'CAGR%':>8}")
    for k, v in summary.items():
        print(f"{k:<18}{v['trades']:>8}{v['winrate']:>9.0%}{v['profit_factor']:>7.2f}"
              f"{v['profit_total_pct']:>10.1f}{v['max_drawdown_account_pct']:>11.1f}{v['cagr_pct']:>8.1f}")
    print("→", RESULTS / "summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
