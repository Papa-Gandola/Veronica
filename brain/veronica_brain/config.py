"""Настройки brain из переменных окружения (см. .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


@dataclass
class Settings:
    dry_run: bool = field(default_factory=lambda: _env("DRY_RUN", "true").lower() not in ("false", "0", "no"))

    # freqtrade REST API
    ft_url: str = field(default_factory=lambda: _env("FT_API_URL", "http://freqtrade:8080"))
    ft_username: str = field(default_factory=lambda: _env("FT_API_USERNAME", "veronica"))
    ft_password: str = field(default_factory=lambda: _env("FT_API_PASSWORD", ""))

    # общая папка с freqtrade (active.json, бэктесты)
    user_data: Path = field(default_factory=lambda: Path(_env("FT_USER_DATA", "/freqtrade/user_data")))
    data_dir: Path = field(default_factory=lambda: Path(_env("BRAIN_DATA_DIR", "/app/data")))

    # риск
    initial_capital: float = field(default_factory=lambda: _env_float("INITIAL_CAPITAL", 100.0))
    max_drawdown: float = field(default_factory=lambda: _env_float("MAX_DRAWDOWN", 0.40))
    max_daily_loss: float = field(default_factory=lambda: _env_float("MAX_DAILY_LOSS", 0.08))

    # расписание
    report_hour_utc: int = field(default_factory=lambda: _env_int("REPORT_HOUR_UTC", 17))
    report_tz: str = field(default_factory=lambda: _env("REPORT_TZ", "Europe/Moscow"))
    poll_seconds: int = field(default_factory=lambda: _env_int("BRAIN_POLL_SECONDS", 60))

    # Claude
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    claude_model: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-opus-5-5"))

    # уведомления
    telegram_token: str = field(default_factory=lambda: _env("TELEGRAM_TOKEN"))
    telegram_chat_id: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_ID"))
    gandola_api_url: str = field(default_factory=lambda: _env("GANDOLA_API_URL").rstrip("/"))
    gandola_username: str = field(default_factory=lambda: _env("GANDOLA_USERNAME"))
    gandola_password: str = field(default_factory=lambda: _env("GANDOLA_PASSWORD"))
    gandola_chat_id: int = field(default_factory=lambda: _env_int("GANDOLA_CHAT_ID", 0))

    # правила смены стратегии
    min_trades_for_verdict: int = field(default_factory=lambda: _env_int("MIN_TRADES_FOR_VERDICT", 15))
    min_days_for_verdict: int = field(default_factory=lambda: _env_int("MIN_DAYS_FOR_VERDICT", 7))
    switch_cooldown_days: int = field(default_factory=lambda: _env_int("SWITCH_COOLDOWN_DAYS", 7))

    @property
    def mode(self) -> str:
        return "dry" if self.dry_run else "live"

    @property
    def active_config_path(self) -> Path:
        return self.user_data / "state" / "active.json"

    @property
    def journal_path(self) -> Path:
        return self.data_dir / "journal.sqlite"

    @property
    def backtests_path(self) -> Path:
        return self.user_data / "backtest_results" / "summary.json"

    @property
    def claude_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def gandola_enabled(self) -> bool:
        return bool(self.gandola_api_url and self.gandola_username and self.gandola_password and self.gandola_chat_id)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


# Стратегии, между которыми brain имеет право переключаться.
STRATEGIES: dict[str, str] = {
    "VeronicaDaily": "дневной пробой канала Дончиана 20/10 над SMA100: редкие сделки, удержание неделями (по умолчанию)",
    "VeronicaTrend": "тренд 1h: вход на откате RSI в растущем рынке (1h и 4h), трейлинг-стоп",
    "VeronicaMeanRev": "возврат к среднему 1h: покупка провала под Боллинджером в растущем режиме 4h",
    "VeronicaBreakout": "пробой канала Дончиана 4h на объёме, долгие удержания",
}
