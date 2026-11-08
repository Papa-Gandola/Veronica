import json
from datetime import datetime, timedelta, timezone

import pytest

from veronica_brain.config import Settings
from veronica_brain.core import Brain
from veronica_brain.journal import Journal
from veronica_brain.notify import Notifier
from veronica_brain.stats import summarize

from fake_ft import FakeFT, make_trade


class CaptureNotifier(Notifier):
    def __init__(self):
        super().__init__(None, None)
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FT_USER_DATA", str(tmp_path / "user_data"))
    monkeypatch.setenv("BRAIN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("INITIAL_CAPITAL", "100")
    monkeypatch.setenv("MAX_DRAWDOWN", "0.40")
    monkeypatch.setenv("MAX_DAILY_LOSS", "0.08")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SWITCH_COOLDOWN_DAYS", "0")
    s = Settings()
    s.active_config_path.parent.mkdir(parents=True)
    s.active_config_path.write_text(json.dumps({"strategy": "VeronicaTrend"}))
    s.backtests_path.parent.mkdir(parents=True)
    s.backtests_path.write_text(json.dumps({
        "VeronicaTrend": {"profit_factor": 1.6, "winrate": 0.55},
        "VeronicaMeanRev": {"profit_factor": 1.4, "winrate": 0.6},
        "VeronicaBreakout": {"profit_factor": 1.8, "winrate": 0.45},
    }))
    ft = FakeFT()
    notifier = CaptureNotifier()
    brain = Brain(s, Journal(s.journal_path), ft, notifier)
    return s, ft, brain, notifier


def test_tick_records_snapshot_and_keeps_running(env):
    s, ft, brain, n = env
    brain.tick()
    assert ft.calls == []
    curve = brain.j.equity_curve()
    assert len(curve) == 1 and curve[0]["equity"] == 100.0


def test_drawdown_halts_and_blocks_manual_restart(env):
    s, ft, brain, n = env
    ft.equity = 59.0  # просадка 41% ≥ 40%
    brain.tick()
    assert "stop" in ft.calls and brain.risk.is_halted()
    assert any("СТОП ПО ПРОСАДКЕ" in m for m in n.sent)
    # кто-то включил бота мимо brain — он останавливает снова
    ft.state = "running"
    brain.tick()
    assert ft.calls.count("stop") == 2


def test_resume_resets_baseline(env):
    s, ft, brain, n = env
    ft.equity = 55.0
    brain.tick()
    assert brain.risk.is_halted()
    reply = brain.command("/resume", "test")
    assert "Продолжаю" in reply and not brain.risk.is_halted()
    assert brain.risk.baseline() == 55.0
    # теперь 40% считаются от 55, и 50 — ещё не стоп
    ft.equity = 50.0
    brain.tick()
    assert not brain.risk.is_halted()


def test_daily_loss_pauses_once(env):
    s, ft, brain, n = env
    brain.tick()                 # фиксируем старт дня = 100
    ft.equity = 91.0             # -9% за день
    brain.tick()
    assert ft.calls == ["pause"]
    brain.tick()                 # повторно не паузим
    assert ft.calls == ["pause"]


def test_sync_trades_and_stats(env):
    s, ft, brain, n = env
    ft.closed = [make_trade(1, 2.0), make_trade(2, -1.0), make_trade(3, 1.5)]
    assert brain.sync_trades(announce=False) == 3
    assert brain.sync_trades(announce=False) == 0
    st = summarize(brain.j.trades_since("2026-01-01"))
    assert st["trades"] == 3 and st["wins"] == 2 and st["profit_factor"] == 3.5


def test_rule_verdict_insufficient_then_switch(env):
    s, ft, brain, n = env
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    # 20 убыточных сделок активной стратегии за последние сутки
    ft.closed = [make_trade(i, -1.0 if i % 5 else 0.5, close_date=recent) for i in range(1, 21)]
    brain.sync_trades(announce=False)
    rv = brain.reviewer.rule_verdict("VeronicaTrend")
    assert rv.verdict == "switch"
    assert rv.recommended == "VeronicaBreakout"  # лучший PF по бэктесту среди остальных

    text = brain.daily_review(force=True)
    assert "reload_config" in ft.calls
    assert json.loads(s.active_config_path.read_text())["strategy"] == "VeronicaBreakout"
    assert "VeronicaTrend → VeronicaBreakout" in text


def test_rule_verdict_insufficient_with_few_trades(env):
    s, ft, brain, n = env
    recent = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ft.closed = [make_trade(i, -1.0, close_date=recent) for i in range(1, 5)]
    brain.sync_trades(announce=False)
    rv = brain.reviewer.rule_verdict("VeronicaTrend")
    assert rv.verdict == "insufficient"


def test_commands(env):
    s, ft, brain, n = env
    assert brain.command("привет всем", "x") is None
    assert "Капитал" in brain.command("Вероника статус", "x")
    assert "VeronicaMeanRev" in brain.command("/strategies", "x")
    reply = brain.command("/strategy VeronicaMeanRev", "x")
    assert "переключена" in reply and ft.calls[-1] == "reload_config"
    assert "неизвестная" in brain.command("/strategy Nope", "x")
    assert "Команды" in brain.command("/help", "x")
