"""Смена активной стратегии: переписать user_data/state/active.json и попросить freqtrade перечитать конфиг."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .config import STRATEGIES, Settings
from .ft_client import FreqtradeClient
from .journal import Journal

log = logging.getLogger("veronica.strategy")


class StrategyManager:
    def __init__(self, settings: Settings, journal: Journal, ft: FreqtradeClient):
        self.s = settings
        self.j = journal
        self.ft = ft

    def active(self) -> str:
        try:
            return json.loads(self.s.active_config_path.read_text())["strategy"]
        except (OSError, KeyError, json.JSONDecodeError):
            return "?"

    def last_switch_at(self) -> datetime | None:
        raw = self.j.get("last_switch_at")
        return datetime.fromisoformat(raw) if raw else None

    def days_since_switch(self) -> float:
        last = self.last_switch_at()
        if not last:
            raw = self.j.get("brain_started_at")
            last = datetime.fromisoformat(raw) if raw else datetime.now(timezone.utc)
        return (datetime.now(timezone.utc) - last).total_seconds() / 86400

    def switch(self, name: str, reason: str) -> str:
        if name not in STRATEGIES:
            raise ValueError(f"неизвестная стратегия {name}; доступны: {', '.join(STRATEGIES)}")
        current = self.active()
        if name == current:
            return f"Стратегия {name} уже активна."
        path = self.s.active_config_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_comment": "Этот файл переписывает brain при смене стратегии.",
            "strategy": name,
            "_switched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "_reason": reason,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=4))
        self.ft.reload_config()
        self.j.set("last_switch_at", datetime.now(timezone.utc).isoformat())
        self.j.add_event("switch", f"{current} → {name}: {reason}")
        log.info("strategy switched %s -> %s (%s)", current, name, reason)
        return f"Стратегия переключена: {current} → {name}.\nПричина: {reason}\nОткрытые сделки доводятся по правилам новой стратегии."
