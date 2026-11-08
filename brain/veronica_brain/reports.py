"""Тексты сообщений для владельца (по-русски)."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .config import Settings


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def local_now(settings: Settings) -> str:
    try:
        tz = ZoneInfo(settings.report_tz)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    return datetime.now(tz).strftime("%d.%m %H:%M")


def status_text(settings: Settings, equity: float, strategy: str, bot_state: str, open_trades: list[dict],
                profit: dict, drawdown: float, halted: bool) -> str:
    mode = "ДЕМО" if settings.mode == "dry" else "РЕАЛ"
    lines = [
        f"Veronica · {mode} · {local_now(settings)}",
        f"Капитал: {equity:.2f} USDT ({_fmt_pct((equity - settings.initial_capital) / settings.initial_capital)} от старта)",
        f"Просадка от базы: {drawdown:.1%} (стоп при {settings.max_drawdown:.0%})",
        f"Стратегия: {strategy} · бот: {bot_state}" + (" · ОСТАНОВЛЕНА ПО РИСКУ" if halted else ""),
        f"Закрыто сделок: {profit.get('closed_trade_count') or 0}, "
        f"winrate {(profit.get('winrate') or 0) * 100:.0f}%, PF {(profit.get('profit_factor') or 0):.2f}",
    ]
    if open_trades:
        lines.append(f"Открыто ({len(open_trades)}):")
        for t in open_trades:
            lines.append(
                f"  • {t['pair']} {_fmt_pct(t.get('profit_ratio') or 0)} "
                f"({t.get('profit_abs') or 0:+.2f} USDT), вход {t.get('enter_tag') or '-'}"
            )
    else:
        lines.append("Открытых сделок нет.")
    return "\n".join(lines)


def trade_closed_text(t: dict) -> str:
    emoji = "🟢" if (t.get("profit_abs") or 0) >= 0 else "🔴"
    dur = t.get("trade_duration")
    dur_s = f"{dur // 60}ч {dur % 60}м" if dur else "-"
    return (
        f"{emoji} Закрыта {t['pair']}: {_fmt_pct(t.get('profit_ratio') or 0)} "
        f"({t.get('profit_abs') or 0:+.2f} USDT), {dur_s}, выход: {t.get('exit_reason') or '-'}"
    )


def daily_report_text(settings: Settings, equity: float, strategy: str, stats_day: dict, stats_7d: dict,
                      rule_reasons: list[str], claude: dict | None, switched: str | None) -> str:
    mode = "ДЕМО" if settings.mode == "dry" else "РЕАЛ"
    lines = [f"📒 Вечерний отчёт Veronica · {mode} · {local_now(settings)}",
             f"Капитал {equity:.2f} USDT · стратегия {strategy}"]
    if stats_day.get("trades"):
        lines.append(
            f"За сутки: {stats_day['trades']} сделок, {stats_day['profit_abs']:+.2f} USDT, "
            f"winrate {stats_day['winrate']:.0%}"
        )
    else:
        lines.append("За сутки сделок не было.")
    if stats_7d.get("trades"):
        lines.append(
            f"За 7 дней: {stats_7d['trades']} сделок, {stats_7d['profit_abs']:+.2f} USDT, "
            f"PF {stats_7d['profit_factor']}, макс. просадка {stats_7d['max_drawdown_abs']:.2f} USDT"
        )
    if rule_reasons:
        lines.append("Правила: " + "; ".join(rule_reasons))
    if claude:
        lines.append("")
        lines.append(claude.get("summary_ru", "").strip())
        if claude.get("reasons"):
            lines.append("Почему: " + "; ".join(claude["reasons"]))
        if claude.get("lesson"):
            lines.append("Урок: " + claude["lesson"])
        lines.append(f"Вердикт: {claude.get('verdict')} (уверенность {claude.get('confidence', 0):.0%})")
    if switched:
        lines.append("")
        lines.append(switched)
    return "\n".join(lines)


HELP_TEXT = """Команды Veronica (в чате или через `docker compose exec brain python -m veronica_brain <cmd>`):
/status — капитал, стратегия, открытые сделки
/report — сделать вечерний отчёт сейчас
/pause — не открывать новые сделки (открытые доводятся)
/resume — снять паузу/стоп по риску и продолжить (база просадки = текущий капитал)
/halt — остановить торговлю до /resume
/strategy <Имя> — переключить стратегию (VeronicaTrend | VeronicaMeanRev | VeronicaBreakout)
/strategies — список стратегий
/help — это сообщение"""
