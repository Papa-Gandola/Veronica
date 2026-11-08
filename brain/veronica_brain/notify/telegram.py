"""Отправка в Telegram через Bot API.

Тем же токеном пользуется и сам freqtrade (он принимает команды). Отправлять
сообщения параллельно можно, принимать (getUpdates) — нельзя, поэтому brain
только пишет. Команды для brain идут через GandolaChat или CLI.
"""

from __future__ import annotations

import httpx


class TelegramSender:
    def __init__(self, token: str, chat_id: str):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self._http = httpx.Client(timeout=15)

    def send(self, text: str) -> None:
        # лимит Telegram — 4096 символов
        for chunk in _chunks(text, 3900):
            r = self._http.post(self.url, json={"chat_id": self.chat_id, "text": chunk})
            r.raise_for_status()


def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]
