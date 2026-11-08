"""Тонкий клиент к REST API freqtrade (JWT-логин, основные ручки)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

log = logging.getLogger("veronica.ft")


class FreqtradeError(RuntimeError):
    pass


class FreqtradeClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._http = httpx.Client(timeout=timeout)
        self._access: str | None = None
        self._access_at: float = 0.0

    # --- auth ---------------------------------------------------------------
    def _login(self) -> None:
        r = self._http.post(f"{self.base_url}/api/v1/token/login", auth=(self.username, self.password))
        if r.status_code != 200:
            raise FreqtradeError(f"login failed: {r.status_code} {r.text[:200]}")
        self._access = r.json()["access_token"]
        self._access_at = time.time()

    def _headers(self) -> dict[str, str]:
        # access-токен живёт 15 минут; перелогиниваемся заранее
        if not self._access or time.time() - self._access_at > 10 * 60:
            self._login()
        return {"Authorization": f"Bearer {self._access}"}

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        url = f"{self.base_url}/api/v1{path}"
        r = self._http.request(method, url, headers=self._headers(), **kw)
        if r.status_code == 401:
            self._login()
            r = self._http.request(method, url, headers=self._headers(), **kw)
        if r.status_code >= 400:
            raise FreqtradeError(f"{method} {path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else None

    # --- info ---------------------------------------------------------------
    def ping(self) -> bool:
        try:
            r = self._http.get(f"{self.base_url}/api/v1/ping")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def show_config(self) -> dict:
        return self._request("GET", "/show_config")

    def balance(self) -> dict:
        return self._request("GET", "/balance")

    def profit(self) -> dict:
        return self._request("GET", "/profit")

    def status(self) -> list[dict]:
        """Открытые сделки."""
        return self._request("GET", "/status")

    def trades(self, limit: int = 50, offset: int = 0) -> dict:
        """Закрытые сделки, новые первыми."""
        return self._request("GET", "/trades", params={"limit": limit, "offset": offset})

    def daily(self, days: int = 7) -> dict:
        return self._request("GET", "/daily", params={"timescale": days})

    def performance(self) -> list[dict]:
        return self._request("GET", "/performance")

    # --- control ------------------------------------------------------------
    def start(self) -> dict:
        return self._request("POST", "/start")

    def stop(self) -> dict:
        return self._request("POST", "/stop")

    def pause(self) -> dict:
        """Не открывать новые сделки, открытые довести до конца."""
        return self._request("POST", "/pause")

    def reload_config(self) -> dict:
        return self._request("POST", "/reload_config")

    def bot_state(self) -> str:
        return str(self.show_config().get("state", "unknown"))

    def strategy(self) -> str:
        return str(self.show_config().get("strategy", "?"))
