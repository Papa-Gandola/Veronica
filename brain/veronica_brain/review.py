"""
Ежедневный разбор.

Два слоя:
1. Правила (работают всегда): по статистике активной стратегии за окно
   решаем, «здорова» ли она. Если нет — предлагаем переключение на
   стратегию с лучшей ожидаемой доходностью по бэктесту, которая ещё не
   проваливалась недавно.
2. Claude (если есть ключ): получает дневник, статистику, бэктесты и вердикт
   правил, пишет человеческий разбор по-русски и своё мнение в строгом JSON.

Переключение применяется только если ОБА слоя согласны (без Claude — только
правила), и не чаще SWITCH_COOLDOWN_DAYS.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field

from .config import STRATEGIES, Settings
from .journal import Journal
from .stats import summarize, window

log = logging.getLogger("veronica.review")

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary_ru": {
            "type": "string",
            "description": "Разбор дня по-русски для владельца: что произошло, что хорошо/плохо, 4-8 предложений, без воды.",
        },
        "verdict": {"type": "string", "enum": ["keep", "tune", "switch"]},
        "recommended_strategy": {
            "type": "string",
            "enum": list(STRATEGIES) + [""],
            "description": "Куда переключиться при verdict=switch, иначе пустая строка.",
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasons": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "lesson": {"type": "string", "description": "Один урок на будущее, одно предложение."},
    },
    "required": ["summary_ru", "verdict", "recommended_strategy", "confidence", "reasons", "lesson"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Ты — Veronica, автономный торговый агент на споте крипты (OKX, без плеча, только лонг),
капитал около 100 USDT. Решения по сделкам принимает код по правилам стратегии; твоя роль — вечерний разбор.
Тебе дают дневник за сутки и окно статистики, параметры бэктестов и вердикт правил.

Правила разбора:
- Опирайся на цифры. Мало сделок — так и скажи: статистической значимости нет, вердикт keep.
- Переключение стратегии (switch) предлагай только при явной деградации: profit factor заметно ниже
  бэктеста на достаточном числе сделок, или серия стопов при режиме рынка, под который стратегия не рассчитана.
- Комиссия на OKX ~0.1% за сторону; частые мелкие сделки съедают депозит — отмечай это.
- Пиши владельцу по-русски, коротко, без восторгов и без обещаний дохода.
- Никогда не предлагай плечо, шорты, усреднение убытков или снятие стопов."""


@dataclass
class RuleVerdict:
    verdict: str                    # keep / switch / insufficient
    recommended: str | None = None
    reasons: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


class Reviewer:
    def __init__(self, settings: Settings, journal: Journal):
        self.s = settings
        self.j = journal
        self._client = None
        if settings.claude_enabled:
            import anthropic  # импорт здесь, чтобы brain работал и без ключа

            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # --- бэктесты как эталон ------------------------------------------------
    def backtests(self) -> dict:
        try:
            return json.loads(self.s.backtests_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    # --- слой 1: правила ----------------------------------------------------
    def rule_verdict(self, strategy: str) -> RuleVerdict:
        since = window(30)
        trades = self.j.trades_since(since, strategy=strategy)
        st = summarize(trades)
        bt = self.backtests().get(strategy, {})
        rv = RuleVerdict(verdict="keep", stats=st)

        if st["trades"] < self.s.min_trades_for_verdict:
            rv.verdict = "insufficient"
            rv.reasons.append(
                f"{st['trades']} сделок за 30 дней — меньше {self.s.min_trades_for_verdict}, выводов пока нет"
            )
            return rv

        ref_pf = float(bt.get("profit_factor") or 1.3)
        ref_wr = float(bt.get("winrate") or 0.5)
        bad = 0
        if st["profit_factor"] < max(0.8, ref_pf * 0.6):
            bad += 1
            rv.reasons.append(f"profit factor {st['profit_factor']} против {ref_pf:.2f} в бэктесте")
        if st["winrate"] < ref_wr * 0.7:
            bad += 1
            rv.reasons.append(f"winrate {st['winrate']:.0%} против {ref_wr:.0%} в бэктесте")
        if st["profit_abs"] < -0.10 * self.s.initial_capital:
            bad += 1
            rv.reasons.append(f"убыток {st['profit_abs']:.2f} USDT за 30 дней (>10% капитала)")

        if bad >= 2:
            rv.verdict = "switch"
            rv.recommended = self._best_alternative(strategy)
            if not rv.recommended:
                rv.verdict = "keep"
                rv.reasons.append("альтернативы недавно тоже проваливались — остаёмся")
        return rv

    def _best_alternative(self, current: str) -> str | None:
        bt = self.backtests()
        recently_failed = set(self.j.get_json("failed_strategies", {}).keys())
        candidates = []
        for name in STRATEGIES:
            if name == current or name in recently_failed:
                continue
            score = float(bt.get(name, {}).get("profit_factor") or 1.0)
            candidates.append((score, name))
        candidates.sort(reverse=True)
        return candidates[0][1] if candidates else None

    def mark_failed(self, strategy: str) -> None:
        failed = self.j.get_json("failed_strategies", {})
        failed[strategy] = window(0)
        # чистим записи старше 30 дней
        cutoff = window(30)
        failed = {k: v for k, v in failed.items() if v >= cutoff}
        self.j.set_json("failed_strategies", failed)

    # --- слой 2: Claude -----------------------------------------------------
    def claude_review(self, context: dict) -> dict | None:
        if not self._client:
            return None
        import anthropic

        user = (
            "Контекст за сутки и окно статистики в JSON ниже. Сделай разбор и верни JSON по схеме.\n\n"
            + json.dumps(context, ensure_ascii=False, indent=1)
        )
        try:
            resp = self._client.messages.create(
                model=self.s.claude_model,
                max_tokens=4000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": REVIEW_SCHEMA}},
            )
        except anthropic.RateLimitError as e:
            log.warning("claude rate limited: %s", e)
            return None
        except anthropic.APIStatusError as e:
            log.warning("claude api error %s: %s", e.status_code, e.message)
            return None
        except anthropic.APIConnectionError as e:
            log.warning("claude connection error: %s", e)
            return None
        if resp.stop_reason == "refusal":
            log.warning("claude refused the review request")
            return None
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            log.warning("claude returned non-json: %s", text[:200])
            return None
        data["_usage"] = {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}
        return data

    # --- сборка контекста ---------------------------------------------------
    def build_context(self, strategy: str, equity: float, bot_state: str, rule: RuleVerdict) -> dict:
        day_trades = self.j.trades_since(window(1))
        return {
            "date_utc": window(0),
            "mode": self.s.mode,
            "active_strategy": strategy,
            "strategies_available": STRATEGIES,
            "bot_state": bot_state,
            "equity_usdt": round(equity, 2),
            "initial_capital": self.s.initial_capital,
            "trades_last_24h": [
                {
                    "pair": t["pair"], "enter_tag": t["enter_tag"], "exit_reason": t["exit_reason"],
                    "profit_abs": t["profit_abs"], "profit_ratio": t["profit_ratio"],
                    "duration_min": t["duration_min"], "close_date": t["close_date"],
                }
                for t in day_trades
            ],
            "stats_7d": summarize(self.j.trades_since(window(7))),
            "stats_30d_active_strategy": rule.stats,
            "backtest_reference": self.backtests(),
            "rule_verdict": asdict(rule),
            "recent_events": self.j.recent_events(10),
            "previous_reviews": [
                {"ts": r["ts"], "verdict": r["verdict"], "summary": r["summary"][:300]} for r in self.j.recent_reviews(3)
            ],
            "equity_curve_7d_sample": self.j.equity_curve(window(7))[::24],
        }
