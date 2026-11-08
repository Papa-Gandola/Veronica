"""
VeronicaBreakout — пробой канала Дончиана на 4h (вариант «черепах»).

Идея: покупаем, когда цена закрывается выше максимума последних 55 свечей
(4h ≈ 9 дней) на повышенном объёме и выше EMA200. Держим, пока цена не
закроется ниже минимума последних 20 свечей или не сработает трейлинг.
Редкие сделки, длинные удержания — мало комиссий, ловит большие движения.
"""

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import DecimalParameter, IntParameter

from veronica_base import VeronicaBase


class VeronicaBreakout(VeronicaBase):
    timeframe = "4h"
    startup_candle_count = 220

    minimal_roi = {"0": 0.40}
    stoploss = -0.08

    trailing_stop = True
    trailing_stop_positive = 0.03
    trailing_stop_positive_offset = 0.08
    trailing_only_offset_is_reached = True

    entry_window = IntParameter(20, 80, default=55, space="buy")
    volume_mult = DecimalParameter(1.0, 2.0, default=1.2, decimals=1, space="buy")
    exit_window = IntParameter(10, 30, default=20, space="sell")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["vol_sma"] = ta.SMA(dataframe["volume"], timeperiod=20)
        for w in self.entry_window.range:
            dataframe[f"dc_high_{w}"] = dataframe["high"].rolling(w).max().shift(1)
        for w in self.exit_window.range:
            dataframe[f"dc_low_{w}"] = dataframe["low"].rolling(w).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dc_high = dataframe[f"dc_high_{self.entry_window.value}"]
        dataframe.loc[
            (dataframe["close"] > dc_high)
            & (dataframe["close"] > dataframe["ema200"])
            & (dataframe["volume"] > dataframe["vol_sma"] * float(self.volume_mult.value))
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "donchian_breakout")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dc_low = dataframe[f"dc_low_{self.exit_window.value}"]
        dataframe.loc[dataframe["close"] < dc_low, ["exit_long", "exit_tag"]] = (1, "channel_break_down")
        return dataframe
