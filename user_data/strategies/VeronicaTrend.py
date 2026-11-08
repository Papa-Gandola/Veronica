"""
VeronicaTrend — трендовая стратегия на 4h с фильтром по дневному графику.

Идея: торгуем только по тренду (EMA50 > EMA200 на 4h и цена выше EMA100 на 1d),
входим на откате — когда RSI возвращается снизу выше порога, а цена снова
над EMA20. Прибыль не фиксируем рано: даём тренду идти, выходим по слому
тренда (закрытие ниже EMA50) или по трейлинг-стопу.
"""

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import DecimalParameter, IntParameter, informative

from veronica_base import VeronicaBase


class VeronicaTrend(VeronicaBase):
    timeframe = "4h"
    startup_candle_count = 220

    minimal_roi = {"0": 0.35}
    stoploss = -0.07

    trailing_stop = True
    trailing_stop_positive = 0.04
    trailing_stop_positive_offset = 0.10
    trailing_only_offset_is_reached = True

    rsi_entry = IntParameter(35, 55, default=45, space="buy")
    adx_min = IntParameter(10, 30, default=18, space="buy")
    exit_ema = IntParameter(30, 60, default=50, space="sell")
    atr_mult = DecimalParameter(0.5, 2.0, default=1.0, decimals=1, space="buy")

    @informative("1d")
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema100"] = ta.EMA(dataframe, timeperiod=100)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        for p in self.exit_ema.range:
            dataframe[f"ema_exit_{p}"] = ta.EMA(dataframe, timeperiod=p)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        uptrend = (dataframe["ema50"] > dataframe["ema200"]) & (dataframe["close"] > dataframe["ema100_1d"])
        pullback_over = (dataframe["rsi"].shift(1) < self.rsi_entry.value) & (dataframe["rsi"] >= self.rsi_entry.value)
        # цена не улетела слишком далеко от EMA20 (не покупаем на пике)
        not_extended = dataframe["close"] < dataframe["ema20"] + float(self.atr_mult.value) * dataframe["atr"]
        dataframe.loc[
            uptrend
            & pullback_over
            & (dataframe["close"] > dataframe["ema20"])
            & not_extended
            & (dataframe["adx"] > self.adx_min.value)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "trend_pullback")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_exit = dataframe[f"ema_exit_{self.exit_ema.value}"]
        dataframe.loc[dataframe["close"] < ema_exit, ["exit_long", "exit_tag"]] = (1, "trend_break")
        return dataframe
