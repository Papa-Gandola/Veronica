# Архитектура Veronica (для разработчика и для Клода)

Два контейнера в `docker-compose.yml`, общая папка `user_data/`.

## freqtrade (движок)

- Образ `freqtradeorg/freqtrade:2025.10`, команда `trade` с двумя конфигами:
  `user_data/config.json` (база, без секретов) + `user_data/state/active.json`
  (только `"strategy": ...`; переписывает brain). Секреты и режим приходят из `.env`
  через переменные `FREQTRADE__<SECTION>__<KEY>` (см. docker-compose.yml).
- Спот, лонг, `max_open_trades: 3`, `stake_amount: unlimited` (капитал делится
  на 3), лимитные ордера, `StaticPairList` из 5 пар.
- `timeframe` в конфиге НЕ задаётся — его определяет стратегия (иначе конфиг
  перекрывает стратегию, и 4h-стратегия начнёт работать на 1h).
- REST API на 8080 внутри сети compose (наружу не пробрасывается). Brain логинится
  basic-auth → JWT (`/api/v1/token/login`).
- `POST /api/v1/reload_config` перечитывает оба конфига и стратегию без перезапуска
  контейнера — так brain меняет стратегию.
- Telegram-бот freqtrade — единственный, кто читает getUpdates этим токеном.
  Brain тем же токеном только отправляет (`sendMessage`), иначе конфликт 409.
- БД сделок: `user_data/tradesv3.dryrun.sqlite` (демо) / `tradesv3.sqlite` (реал).

## brain (`brain/veronica_brain/`)

| Модуль | Зачем |
|---|---|
| `__main__.py` | CLI и главный цикл: каждые `BRAIN_POLL_SECONDS` (60) — `tick()`; в `REPORT_HOUR_UTC` — `daily_review()`; параллельно слушает GandolaChat |
| `core.py` | `Brain`: снимок (`balance`, `profit`, `status`, `show_config`), синк сделок, риск-правила, вечерний разбор, обработка команд |
| `risk.py` | стоп по просадке от базы (`dd_baseline` в kv), дневной лимит (`day_start`), флаг `halted` |
| `review.py` | слой правил (`rule_verdict`) + Claude (`claude_review`, structured output по `REVIEW_SCHEMA`) + сборка контекста |
| `strategy_manager.py` | запись `active.json` + `reload_config`, кулдаун смен |
| `journal.py` | SQLite: `snapshots`, `trades`, `events`, `reviews`, `kv` |
| `stats.py` | winrate / profit factor / просадка по списку сделок без pandas |
| `reports.py` | тексты сообщений (русский) |
| `notify/telegram.py` | `sendMessage` |
| `notify/gandola.py` | логин → JWT, WS `/ws?token=`, отправка `{"type":"message",...}`, приём команд из своего чата |
| `ft_client.py` | httpx-клиент к REST freqtrade |

Состояние brain живёт в volume `brain_data` (`/app/data/journal.sqlite`). Ключи kv:
`dd_baseline`, `halted`, `day_start`, `paused_day`, `last_report_day`,
`last_switch_at`, `failed_strategies`, `brain_started_at`, `trades_synced_once`.

### Правила смены стратегии (review.py)

1. Окно 30 дней по активной стратегии. Меньше `MIN_TRADES_FOR_VERDICT` (15) сделок → `insufficient`.
2. Сравнение с `user_data/backtest_results/summary.json` (эталон из бэктеста):
   PF < max(0.8, 0.6·PF_бэктест); winrate < 0.7·winrate_бэктест; убыток > 10% капитала.
   Два из трёх → `switch` на стратегию с лучшим PF по бэктесту, не из `failed_strategies`
   (провалившиеся за последние 30 дней).
3. Claude (если ключ) получает контекст и возвращает JSON `{summary_ru, verdict, recommended_strategy,
   confidence, reasons, lesson}`. Переключение — только если правила сказали `switch`
   и Claude сказал `switch` с confidence ≥ 0.7. Без Claude — по правилам.
4. Не чаще `SWITCH_COOLDOWN_DAYS` (7), и не во время `halted`.

### Команды (GandolaChat / CLI)

`/status /report /pause /resume /halt /strategy <Имя> /strategies /help`,
также «Вероника статус». CLI: `docker compose exec brain python -m veronica_brain <cmd>`.

## Стратегии (`user_data/strategies/`)

Все наследуют `VeronicaBase` (`veronica_base.py`): лонг-only, лимитные ордера,
защиты CooldownPeriod / StoplossGuard / MaxDrawdown, ограниченные пространства
hyperopt для стопа и трейлинга (иначе оптимизатор выбирает стоп −35%).

Параметры стратегий подбирались hyperopt'ом на 2022-01 → 2024-06 и проверялись
на 2024-07 → сегодня (out-of-sample). Детали — `docs/BACKTESTS.md`.

## Грабли

- `docker compose restart` не перечитывает `.env` — только `up -d`.
- Образ freqtrade работает от пользователя `ftuser` (uid 1000); папка `user_data/`
  должна быть ему доступна на запись (на Ubuntu-VM пользователь `ubuntu` = uid 1000, ок).
- На Always Free VM с 1 ГБ RAM без свопа freqtrade может быть убит OOM — скрипт
  `scripts/oracle-setup.sh` добавляет 2 ГБ свопа.
- В sandbox-окружении без прямого выхода в сеть freqtrade/ccxt игнорируют
  `HTTPS_PROXY`; нужен `ccxt_config.httpsProxy` в локальном конфиге
  (`user_data/config.local.json`, в git не попадает).
