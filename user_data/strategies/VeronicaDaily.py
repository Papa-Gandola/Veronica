"""
VeronicaDaily — дневной пробой канала Дончиана (20/10) с фильтром SMA100.

Идея «черепах» на дневном графике: покупаем, когда цена закрывается выше
максимума последних 20 дней и выше SMA100 (долгосрочный тренд вверх);
выходим, когда цена закрывается ниже минимума последних 10 дней. Очень
мало сделок (десятки в год на 5 пар), удержание неделями, комиссии не
важны. Параметры НЕ подбирались hyperopt'ом — это классические значения;
в бэктесте стратегия единственная показала плюс и на обучающем, и на
проверочном периоде (см. docs/BACKTESTS.md). Стратегия по умолчанию.
"""

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import IntParameter

from veronica_base import VeronicaBase


class VeronicaDaily(VeronicaBase):
    timeframe = "1d"
    startup_candle_count = 120

    minimal_roi = {"0": 10}  # прибыль не фиксируем — выход только по сигналу/стопу
    stoploss = -0.10
    trailing_stop = False

    entry_window = IntParameter(15, 40, default=20, space="buy", optimize=False)
    exit_window = IntParameter(5, 20, default=10, space="sell", optimize=False)
    sma_period = IntParameter(50, 200, default=100, space="buy", optimize=False)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sma"] = ta.SMA(dataframe, timeperiod=self.sma_period.value)
        dataframe["dc_high"] = dataframe["high"].rolling(self.entry_window.value).max().shift(1)
        dataframe["dc_low"] = dataframe["low"].rolling(self.exit_window.value).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] > dataframe["dc_high"])
            & (dataframe["close"] > dataframe["sma"])
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "donchian_20d")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["close"] < dataframe["dc_low"], ["exit_long", "exit_tag"]] = (1, "channel_10d_down")
        return dataframe
