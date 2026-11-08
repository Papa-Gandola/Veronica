"""
Клиент GandolaChat. Veronica — обычный пользователь чата.

Протокол (см. docs/ARCHITECTURE.md в репозитории gandolachat):
- POST /api/auth/login  {username, password} → {access_token}
- WS   /ws?token=<jwt>; отправка: {"type":"message","chat_id":N,"content":"..."}
- входящие: {"type":"message","id","chat_id","sender_id","sender_username","content",...}

Отправка идёт через короткоживущее WS-соединение (открыть → послать →
закрыть), приём команд — через отдельное долгоживущее соединение в
asyncio-задаче (listen).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Awaitable, Callable

import httpx
import websockets

log = logging.getLogger("veronica.gandola")

CommandHandler = Callable[[str, str], Awaitable[str | None]]  # (text, sender_username) -> reply


class GandolaClient:
    def __init__(self, api_url: str, username: str, password: str, chat_id: int):
        self.api_url = api_url.rstrip("/")
        self.username = username
        self.password = password
        self.chat_id = chat_id
        self._token: str | None = None
        self._token_at = 0.0
        self._my_id: int | None = None

    # --- auth ---------------------------------------------------------------
    def _login(self) -> str:
        r = httpx.post(
            f"{self.api_url}/api/auth/login",
            json={"username": self.username, "password": self.password},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._my_id = data.get("user", {}).get("id")
        self._token_at = time.time()
        return self._token

    def token(self) -> str:
        # JWT живёт 7 дней; обновляем раз в сутки
        if not self._token or time.time() - self._token_at > 24 * 3600:
            return self._login()
        return self._token

    @property
    def ws_url(self) -> str:
        base = self.api_url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base}/ws?token={self.token()}"

    # --- send ---------------------------------------------------------------
    def send(self, text: str) -> None:
        asyncio.run(self._send_async(text))

    async def _send_async(self, text: str) -> None:
        async with websockets.connect(self.ws_url, open_timeout=15) as ws:
            await ws.send(json.dumps({"type": "message", "chat_id": self.chat_id, "content": text}))
            # даём серверу принять кадр до закрытия
            await asyncio.sleep(0.3)

    # --- listen -------------------------------------------------------------
    async def listen(self, on_command: CommandHandler, stop: asyncio.Event) -> None:
        """Слушаем свой чат, реагируем на сообщения-команды. Реконнект с бэкоффом."""
        backoff = 2
        while not stop.is_set():
            try:
                async with websockets.connect(self.ws_url, open_timeout=15, ping_interval=25) as ws:
                    log.info("gandola: connected, listening chat %s", self.chat_id)
                    backoff = 2
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=60)
                        except asyncio.TimeoutError:
                            await ws.send(json.dumps({"type": "ping", "t": int(time.time() * 1000)}))
                            continue
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if data.get("type") != "message" or data.get("chat_id") != self.chat_id:
                            continue
                        if self._my_id is not None and data.get("sender_id") == self._my_id:
                            continue
                        content = (data.get("content") or "").strip()
                        if not content:
                            continue
                        reply = await on_command(content, data.get("sender_username") or "?")
                        if reply:
                            await ws.send(json.dumps({"type": "message", "chat_id": self.chat_id, "content": reply}))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("gandola listen error: %s; reconnect in %ss", e, backoff)
                self._token = None  # на случай протухшего токена
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 120)
