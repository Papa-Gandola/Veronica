"""Каналы уведомлений: Telegram (отправка) и GandolaChat (отправка + команды)."""

from __future__ import annotations

import logging

from .gandola import GandolaClient
from .telegram import TelegramSender

log = logging.getLogger("veronica.notify")


class Notifier:
    """Рассылает одно и то же сообщение во все включённые каналы."""

    def __init__(self, telegram: TelegramSender | None, gandola: GandolaClient | None):
        self.telegram = telegram
        self.gandola = gandola

    def send(self, text: str) -> None:
        log.info("notify: %s", text.replace("\n", " | ")[:200])
        if self.telegram:
            try:
                self.telegram.send(text)
            except Exception as e:  # noqa: BLE001 — уведомления не должны валить цикл
                log.warning("telegram send failed: %s", e)
        if self.gandola:
            try:
                self.gandola.send(text)
            except Exception as e:  # noqa: BLE001
                log.warning("gandola send failed: %s", e)
