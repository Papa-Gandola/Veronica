# Veronica — автономный торговый агент (спот, OKX)

Veronica торгует криптой на споте OKX небольшим депозитом (~100 USDT), без плеча и
шортов: счёт физически не может уйти в минус. Торгует по правилам стратегии, ведёт
дневник, вечером разбирает день (при желании — с помощью Claude), при деградации
стратегии переключается на другую, при большой просадке останавливается и ждёт
человека. Общается через Telegram и GandolaChat.

> Честно: ни один бот не гарантирует доход. Задача Veronica — торговать
> дисциплинированно, не слить всё за день и накопить статистику, по которой
> видно, что работает, а что нет. Сначала демо, потом реальные 100 долларов.

## Как устроено

```
┌────────────────────────┐  REST (внутри compose)  ┌──────────────────────────┐
│  freqtrade             │◄────────────────────────│  brain (Veronica)        │
│  стратегии, ордера,    │                         │  надзор каждую минуту:   │
│  стопы, ROI, защиты,   │  user_data/state/       │   • снимок капитала      │
│  Telegram-команды      │  active.json ──────────►│   • стоп по просадке 40% │
│  (/status /profit ...) │  (какая стратегия)      │   • дневной лимит 8%     │
└───────────┬────────────┘                         │  вечером (20:00 МСК):    │
            │ ccxt                                 │   • отчёт + разбор Claude│
            ▼                                      │   • смена стратегии      │
         OKX spot                                  │  GandolaChat: команды    │
                                                   └──────────────────────────┘
```

- **freqtrade** — зрелый open-source движок. Он и только он выставляет ордера.
- **brain** — наш код (`brain/`). Он не торгует сам: смотрит, считает, останавливает,
  переключает стратегии (переписывает `active.json` и просит freqtrade перечитать конфиг),
  пишет отчёты. Решения по сделкам всегда принимает код стратегии, а не нейросеть.
- **Стратегии** (`user_data/strategies/`), между которыми brain переключается:

| Стратегия | Таймфрейм | Идея |
|---|---|---|
| `VeronicaDaily` **(по умолчанию)** | 1d | пробой 20-дневного максимума над SMA100, выход ниже 10-дневного минимума; редкие сделки, удержание неделями |
| `VeronicaBreakout` | 4h | пробой канала Дончиана на объёме, трейлинг-стоп |
| `VeronicaTrend` | 4h (+1d фильтр) | по тренду, вход на откате RSI, выход по слому тренда |
| `VeronicaMeanRev` | 4h (+1d фильтр) | покупка провала под Боллинджером в растущем режиме |

Все: только лонг, 3 позиции максимум, лимитные ордера (комиссия maker 0.10%),
стоп-лосс рыночный −7…−12%, защиты после серии стопов. Результаты бэктестов с 2022
года и честные выводы — в `docs/BACKTESTS.md`. Коротко: на проверочном периоде
2024–2026 в плюсе только `VeronicaDaily` (+5%), остальные в минусе; ни одна не
обгоняет простое удержание монет.

## Этапы

1. **Бэктест** — уже сделан (см. `docs/BACKTESTS.md`), пересчитать: `scripts/backtest.sh`.
2. **Демо (`DRY_RUN=true`)** — freqtrade торгует виртуальными 100 USDT по реальным
   ценам OKX. Ключи биржи не нужны. Рекомендация: минимум 3–4 недели.
3. **Реал (`DRY_RUN=false`)** — те же стратегии, реальные 100 USDT. Переключение —
   осознанно, руками, см. ниже.

## Установка на Oracle Cloud Always Free (бесплатно)

Нужен сервер, который работает 24/7. Бесплатный вариант — Oracle Cloud.

1. Зарегистрируйся на cloud.oracle.com (нужна карта для проверки, деньги не списывают,
   пока не перейдёшь на платный тариф явно).
2. **Compute → Instances → Create instance.** Image: Ubuntu 24.04. Shape: *Always Free*
   (VM.Standard.E2.1.Micro, 1 ГБ RAM — хватает; если дадут ARM Ampere A1 — ещё лучше).
   Скачай SSH-ключ при создании.
3. Подключись: `ssh -i ключ.key ubuntu@<публичный IP>`.
4. Поставь всё одним скриптом и склонируй репозиторий:

```bash
sudo apt-get install -y git
git clone https://github.com/Papa-Gandola/Veronica.git
cd Veronica
bash scripts/oracle-setup.sh
```

5. Выйди и зайди по ssh снова (чтобы docker работал без sudo).

Подойдёт и любой другой VPS с Ubuntu — скрипт тот же.

## Настройка

```bash
cp .env.example .env
nano .env
```

Минимум для демо: придумать `FT_API_PASSWORD`, `FT_JWT_SECRET`, `FT_WS_TOKEN`
(любые случайные строки, например `openssl rand -hex 32`). Остальное по желанию:

### Telegram (рекомендую)
1. В Telegram открой **@BotFather** → `/newbot` → получи токен.
2. Открой **@userinfobot** → он скажет твой `chat_id`.
3. В `.env`: `TELEGRAM_ENABLED=true`, `TELEGRAM_TOKEN=...`, `TELEGRAM_CHAT_ID=...`.
4. Напиши своему боту `/start` после запуска. Команды freqtrade: `/status`, `/profit`,
   `/balance`, `/daily`, `/performance`, `/stop`, `/start`, `/forceexit`, `/help`.
   Brain тоже пишет туда отчёты и предупреждения.

### GandolaChat
1. Зарегистрируй в своём чате пользователя `Veronica` и одобри его как админ.
2. Добавь её в чат (личный или групповой), узнай `id` чата (в URL/инфо чата или через
   `GET /api/chats` под её токеном).
3. В `.env`: `GANDOLA_API_URL=https://2-26-117-77.sslip.io`, логин, пароль, `GANDOLA_CHAT_ID`.
4. В чате Veronica понимает команды: `/status`, `/report`, `/pause`, `/resume`, `/halt`,
   `/strategy VeronicaBreakout`, `/strategies`, `/help`. Можно по-русски: «Вероника статус».

### Claude (вечерний разбор)
Ключ с console.anthropic.com → `ANTHROPIC_API_KEY=`. Один разбор в сутки на
`claude-opus-5-5` стоит примерно 5–10 центов, то есть 2–4 доллара в месяц. Без ключа
всё работает, просто разбор будет только по правилам, без текста.

## Запуск

```bash
docker compose up -d --build
docker compose logs -f brain
```

Через минуту в Telegram/чат придёт «Veronica запущена · режим ДЕМО ...».

Полезное:

```bash
docker compose logs -f freqtrade              # что делает движок
docker compose exec brain python -m veronica_brain status
docker compose exec brain python -m veronica_brain report
docker compose exec brain python -m veronica_brain resume
docker compose exec brain python -m veronica_brain strategy VeronicaBreakout
docker compose restart brain                  # после правок brain: up -d --build
```

Обновление кода на сервере:

```bash
git pull && docker compose up -d --build
```

## Что делает brain по риску

| Правило | Что происходит | Как снять |
|---|---|---|
| Просадка ≥ `MAX_DRAWDOWN` (40%) от базы | `stop`: торговля остановлена, ордера отменены, уведомление | `/resume` — база просадки становится текущим капиталом |
| Убыток за день (UTC) ≥ `MAX_DAILY_LOSS` (8%) | `pause`: новых входов нет, открытые доводятся | само, в 00:00 UTC |
| Кто-то включил бота, пока стоит стоп по риску | brain останавливает снова и пишет об этом | `/resume` |
| Внутри freqtrade | CooldownPeriod, StoplossGuard (3 стопа по паре → пара отдыхает), MaxDrawdown 10%/7д → пауза 2 дня | само |

## Как Veronica «учится»

Каждый вечер (`REPORT_HOUR_UTC`, по умолчанию 20:00 МСК):

1. **Правила** смотрят на активную стратегию за 30 дней: profit factor, winrate,
   убыток — и сравнивают с её бэктестом (`user_data/backtest_results/summary.json`).
   Меньше 15 сделок — выводов нет. Два из трёх показателей провалены — вердикт
   «переключить» на стратегию с лучшим PF по бэктесту, которая не проваливалась
   в последние 30 дней.
2. **Claude** (если включён) получает дневник за сутки, статистику, бэктесты, вердикт
   правил и возвращает разбор по-русски + своё мнение в строгом JSON.
3. Переключение применяется, только если согласны и правила, и Claude (уверенность ≥ 70%),
   и с прошлой смены прошло ≥ `SWITCH_COOLDOWN_DAYS` (7). Без Claude — только правила.
4. Всё записывается в дневник (`brain_data` volume, SQLite): снимки капитала каждую
   минуту, сделки, события, разборы.

Переключить руками можно всегда: `/strategy VeronicaMeanRev`.

## Переход на реальные деньги

Только когда демо несколько недель показывает вменяемый результат.

1. На OKX: **Profile → API → Create API key.** Права: **Read + Trade**. Галочку
   **Withdraw НЕ ставить.** Passphrase придумай и сохрани. По желанию — привязать к
   IP сервера. Ключ бесплатный.
2. Положи на спот-счёт OKX ~100 USDT (именно на *Trading account*, не Funding).
3. В `.env`: `DRY_RUN=false`, `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_API_PASSPHRASE`,
   `INITIAL_CAPITAL=100`.
4. `docker compose up -d` (именно `up`, а не `restart` — иначе старый env останется).
5. Убедись, что пришло сообщение «режим РЕАЛЬНЫЕ ДЕНЬГИ».

База данных сделок для демо и реала разная (`tradesv3.dryrun.sqlite` / `tradesv3.sqlite`),
статистика не смешается. Дневник brain общий — при переходе на реал имеет смысл
очистить volume: `docker compose down -v` (сделки freqtrade при этом сохранятся,
они в `user_data/`).

## Стоимость

| Что | Сколько |
|---|---|
| Сервер Oracle Always Free | 0 |
| OKX API-ключ | 0 |
| Комиссии OKX | 0.10% maker / 0.15% taker за сторону |
| Claude (разбор раз в сутки) | ~2–4 $/мес, можно отключить |

## Структура репозитория

```
docker-compose.yml        freqtrade + brain
.env.example              все настройки с комментариями
user_data/config.json     базовый конфиг freqtrade (без секретов)
user_data/state.default.json  стратегия по умолчанию (копируется в state/active.json)
user_data/strategies/     VeronicaDaily / VeronicaBreakout / VeronicaTrend / VeronicaMeanRev (+ *.json — параметры из hyperopt)
brain/veronica_brain/     код надзора: core, risk, review, journal, strategy_manager, notify/
brain/tests/              юнит-тесты (pytest)
scripts/oracle-setup.sh   подготовка сервера
scripts/backtest.sh       пересчёт бэктестов и эталона summary.json
docs/BACKTESTS.md         результаты бэктестов и как их читать
docs/ARCHITECTURE.md      устройство brain, правила смены стратегий, грабли
```

## Разработка

```bash
# тесты brain
cd brain && pip install -r requirements.txt pytest && python -m pytest -q tests

# бэктест локально (нужен freqtrade: pip install freqtrade, или через docker — scripts/backtest.sh)
freqtrade backtesting --config user_data/config.json --userdir user_data \
  --strategy VeronicaDaily --timeframe 1d --timerange 20240101-
```
