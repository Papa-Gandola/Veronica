#!/usr/bin/env bash
# Бэктест всех стратегий на истории с 2022 года + обновление эталона summary.json для brain.
# Использование: scripts/backtest.sh            (скачает недостающие данные и прогонит всё)
#                scripts/backtest.sh 20240101-  (свой timerange)
set -euo pipefail
cd "$(dirname "$0")/.."
RANGE="${1:-20220101-}"
FT="docker compose run --rm --no-deps freqtrade"

$FT download-data --config /freqtrade/user_data/config.json --timerange "$RANGE" --timeframes 1h 4h 1d
$FT backtesting --config /freqtrade/user_data/config.json --strategy-list VeronicaTrend VeronicaMeanRev \
    --timerange "$RANGE" --export trades --cache none
$FT backtesting --config /freqtrade/user_data/config.json --strategy VeronicaBreakout \
    --timerange "$RANGE" --export trades --cache none

python3 scripts/summarize_backtests.py
