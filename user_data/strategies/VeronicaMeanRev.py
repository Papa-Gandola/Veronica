"""
VeronicaMeanRev — возврат к среднему на 4h внутри бычьего режима по 1d.

Идея: в растущем рынке (EMA50 > EMA200 на 1d) покупаем резкие провалы —
RSI(14) на 4h перепродан и цена ниже нижней полосы Боллинджера. Выход —
RSI вернулся выше порога или цена дошла до средней полосы, либо ROI.
На 4h сделок в разы меньше, чем на 1h, и комиссия не съедает результат.
"""

import talib.abstract as ta
from pandas import DataFrame

import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.strategy import DecimalParameter, IntParameter, informative

from veronica_base import VeronicaBase


class VeronicaMeanRev(VeronicaBase):
    timeframe = "4h"
    startup_candle_count = 220

    minimal_roi = {"0": 0.08, "48": 0.04, "120": 0.015}
    stoploss = -0.07
    trailing_stop = False

    rsi_entry = IntParameter(20, 38, default=30, space="buy")
    bb_std = DecimalParameter(1.8, 2.6, default=2.0, decimals=1, space="buy")
    rsi_exit = IntParameter(50, 70, default=58, space="sell")

    @informative("1d")
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        for std in self.bb_std.range:
            bb = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=float(std))
            dataframe[f"bb_lower_{std}"] = bb["lower"]
        bb_mid = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2.0)
        dataframe["bb_mid"] = bb_mid["mid"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        regime_up = dataframe["ema50_1d"] > dataframe["ema200_1d"]
        lower = dataframe[f"bb_lower_{self.bb_std.value}"]
        dataframe.loc[
            regime_up
            & (dataframe["close"] < lower)
            & (dataframe["rsi"] < self.rsi_entry.value)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "bb_dip")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] > dataframe["bb_mid"]) | (dataframe["rsi"] > self.rsi_exit.value),
            ["exit_long", "exit_tag"],
        ] = (1, "back_to_mean")
        return dataframe
