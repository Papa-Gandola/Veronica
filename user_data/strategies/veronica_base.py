"""
Общая часть стратегий Veronica.

Все стратегии — только спот, только лонг (без плеча и шортов: счёт не может
уйти в минус). Защиты (protections) одинаковые: после серии стопов пара
отдыхает, при просадке по всем парам бот берёт паузу.
"""

from freqtrade.strategy import IStrategy


class VeronicaBase(IStrategy):
    INTERFACE_VERSION = 3

    can_short = False
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # Лимитные ордера: на OKX это maker-комиссия 0.10% против 0.15% по рынку.
    # Стоп-лосс — рыночный, чтобы гарантированно выйти.
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    @property
    def protections(self):
        return [
            # После закрытия сделки по паре — 2 свечи тишины, чтобы не перезаходить тут же.
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            # 3 стопа по одной паре за 48 свечей → пара отдыхает 24 свечи.
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,
                "trade_limit": 3,
                "stop_duration_candles": 24,
                "only_per_pair": True,
            },
            # Просадка 10% по всем сделкам за 7 дней → стоп всем входам на 2 дня.
            {
                "method": "MaxDrawdown",
                "lookback_period": 7 * 24 * 60,
                "trade_limit": 4,
                "stop_duration": 48 * 60,
                "max_allowed_drawdown": 0.10,
            },
        ]

    class HyperOpt:
        """
        Границы для hyperopt. Без них оптимизатор «находит» стоп −35% и
        трейлинг 30%: на бычьем участке истории это выглядит прибыльно, а
        в жизни — один стоп съедает треть депозита. Держим стоп в разумных
        рамках и запрещаем экстремальные трейлинги.
        """

        @staticmethod
        def stoploss_space():
            from freqtrade.optimize.space import SKDecimal

            return [SKDecimal(-0.12, -0.04, decimals=3, name="stoploss")]

        @staticmethod
        def trailing_space():
            from freqtrade.optimize.space import Categorical, SKDecimal

            return [
                Categorical([True], name="trailing_stop"),
                SKDecimal(0.02, 0.08, decimals=3, name="trailing_stop_positive"),
                # смещение = positive + p1; итого активация трейлинга от +3% до +18%
                SKDecimal(0.01, 0.10, decimals=3, name="trailing_stop_positive_offset_p1"),
                Categorical([True, False], name="trailing_only_offset_is_reached"),
            ]
