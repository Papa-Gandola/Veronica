"""
Точка входа brain.

  python -m veronica_brain run              — основной цикл (в docker)
  python -m veronica_brain status|report|pause|resume|halt|strategies
  python -m veronica_brain strategy VeronicaMeanRev
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time

from .config import Settings
from .core import Brain
from .ft_client import FreqtradeClient
from .journal import Journal
from .notify import Notifier
from .notify.gandola import GandolaClient
from .notify.telegram import TelegramSender

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("veronica")


def build() -> tuple[Settings, Brain]:
    s = Settings()
    journal = Journal(s.journal_path)
    ft = FreqtradeClient(s.ft_url, s.ft_username, s.ft_password)
    telegram = TelegramSender(s.telegram_token, s.telegram_chat_id) if s.telegram_enabled else None
    gandola = (
        GandolaClient(s.gandola_api_url, s.gandola_username, s.gandola_password, s.gandola_chat_id)
        if s.gandola_enabled
        else None
    )
    return s, Brain(s, journal, ft, Notifier(telegram, gandola))


async def run_loop(s: Settings, brain: Brain) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    # ждём, пока freqtrade поднимется
    for _ in range(60):
        if brain.ft.ping():
            break
        log.info("жду freqtrade на %s ...", s.ft_url)
        await asyncio.sleep(5)

    mode = "ДЕМО (dry-run)" if s.mode == "dry" else "РЕАЛЬНЫЕ ДЕНЬГИ"
    brain.notify.send(
        f"🤖 Veronica запущена · режим {mode} · стратегия {brain.strategies.active()} · "
        f"стоп по просадке {s.max_drawdown:.0%} · Claude {'вкл' if s.claude_enabled else 'выкл'}"
    )

    tasks = []
    if brain.notify.gandola:
        async def on_command(text: str, who: str) -> str | None:
            return await asyncio.to_thread(brain.command, text, who)

        tasks.append(asyncio.create_task(brain.notify.gandola.listen(on_command, stop)))

    async def supervise() -> None:
        while not stop.is_set():
            try:
                await asyncio.to_thread(brain.tick)
                if brain.report_due():
                    await asyncio.to_thread(brain.daily_review)
            except Exception as e:  # noqa: BLE001 — цикл надзора не должен умирать
                log.exception("tick failed: %s", e)
            try:
                await asyncio.wait_for(stop.wait(), timeout=s.poll_seconds)
            except asyncio.TimeoutError:
                pass

    tasks.append(asyncio.create_task(supervise()))
    await stop.wait()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("brain stopped")


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "run"
    s, brain = build()
    if cmd == "run":
        asyncio.run(run_loop(s, brain))
        return 0
    # разовые команды из CLI
    text = "/" + " ".join(argv[1:])
    t0 = time.time()
    reply = brain.command(text, who="cli")
    if reply is None:
        print(f"неизвестная команда: {cmd}", file=sys.stderr)
        return 2
    print(reply)
    log.debug("done in %.1fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
