"""A股交易成本计算模型。"""

from dataclasses import dataclass


@dataclass
class TransactionCostConfig:
    """A股交易成本配置。

    默认值基于A股典型收费标准:
    - 佣金: 万三 (0.03%) 标准费率，量化优待万一 (0.01%)
    - 最低佣金: 5元（规避小额交易陷阱）
    - 印花税: 万五 (0.05%)，仅卖出方收取
    - 过户费: 万一至万二 (0.0001~0.0002%)，沪市股票双向收取
    """

    commission_rate: float = 0.0003     # 佣金率 0.03% (标准)，量化优待可用0.0001
    commission_min: float = 5.0         # 最低佣金 5元
    stamp_duty_rate: float = 0.0005     # 印花税率 0.05% (仅卖出)
    transfer_fee_rate: float = 0.0001   # 过户费率 0.01% (沪市，范围0.0001~0.0002)

    # 是否为沪市股票（6开头为沪市，0/3开头为深市）
    sh_market: bool = True


class TransactionCostCalculator:
    """A股交易成本计算器。"""

    def __init__(self, config: TransactionCostConfig | None = None):
        """
        初始化计算器。

        参数：
            config: 交易成本配置，默认使用A股典型值。
        """
        self.config = config or TransactionCostConfig()

    def calculate_buy_costs(
        self,
        price: float,
        quantity: int,
        sh_market: bool | None = None,
    ) -> dict[str, float]:
        """
        计算买入交易成本。

        参数：
            price: 买入价格。
            quantity: 买入数量（股）。
            sh_market: 是否沪市股票，None则根据config判断。

        返回：
            dict: 包含各项成本和有效价格。
        """
        trade_value = price * quantity

        # 佣金
        commission = trade_value * self.config.commission_rate
        commission = max(commission, self.config.commission_min)

        # 过户费（沪市双向收取）
        is_sh = sh_market if sh_market is not None else self.config.sh_market
        transfer_fee = trade_value * self.config.transfer_fee_rate if is_sh else 0.0

        # 印花税（买入不收）
        stamp_duty = 0.0

        total_cost = commission + transfer_fee + stamp_duty
        effective_price = (trade_value + total_cost) / quantity

        return {
            "trade_value": trade_value,
            "commission": commission,
            "stamp_duty": stamp_duty,
            "transfer_fee": transfer_fee,
            "total_cost": total_cost,
            "effective_price": effective_price,
        }

    def calculate_sell_costs(
        self,
        price: float,
        quantity: int,
        sh_market: bool | None = None,
    ) -> dict[str, float]:
        """
        计算卖出交易成本。

        参数：
            price: 卖出价格。
            quantity: 卖出数量（股）。
            sh_market: 是否沪市股票，None则根据config判断。

        返回：
            dict: 包含各项成本和有效价格。
        """
        trade_value = price * quantity

        # 佣金
        commission = trade_value * self.config.commission_rate
        commission = max(commission, self.config.commission_min)

        # 过户费（沪市双向收取）
        is_sh = sh_market if sh_market is not None else self.config.sh_market
        transfer_fee = trade_value * self.config.transfer_fee_rate if is_sh else 0.0

        # 印花税（卖出收取）
        stamp_duty = trade_value * self.config.stamp_duty_rate

        total_cost = commission + transfer_fee + stamp_duty
        effective_price = (trade_value - total_cost) / quantity

        return {
            "trade_value": trade_value,
            "commission": commission,
            "stamp_duty": stamp_duty,
            "transfer_fee": transfer_fee,
            "total_cost": total_cost,
            "effective_price": effective_price,
        }

    def calculate_total_costs(
        self,
        entry_price: float,
        exit_price: float,
        quantity: int,
        sh_market: bool | None = None,
    ) -> dict[str, float]:
        """
        计算完整交易周期的总成本（买入+卖出）。

        参数：
            entry_price: 入场价格。
            exit_price: 出场价格。
            quantity: 交易数量。
            sh_market: 是否沪市股票。

        返回：
            dict: 总成本汇总。
        """
        buy_costs = self.calculate_buy_costs(entry_price, quantity, sh_market)
        sell_costs = self.calculate_sell_costs(exit_price, quantity, sh_market)

        return {
            "buy_cost": buy_costs["total_cost"],
            "sell_cost": sell_costs["total_cost"],
            "total_cost": buy_costs["total_cost"] + sell_costs["total_cost"],
            "commission_total": buy_costs["commission"] + sell_costs["commission"],
            "stamp_duty_total": sell_costs["stamp_duty"],
            "transfer_fee_total": buy_costs["transfer_fee"] + sell_costs["transfer_fee"],
        }

    def is_sh_market(self, symbol: str) -> bool:
        """
        根据股票代码判断是否为沪市股票。

        参数：
            symbol: 股票代码。

        返回：
            bool: 是否沪市股票。
        """
        # 沪市股票代码以6开头
        return symbol.startswith("6")


def calculate_net_return(
    entry_price: float,
    exit_price: float,
    quantity: int,
    config: TransactionCostConfig | None = None,
) -> dict[str, float]:
    """
    计算扣除成本后的净收益率。

    参数：
        entry_price: 入场价格。
        exit_price: 出场价格。
        quantity: 交易数量。
        config: 交易成本配置。

    返回：
        dict: 收益率详情。
    """
    calc = TransactionCostCalculator(config)

    # 判断市场
    # 假设symbol以6开头为沪市（实际调用时应传入symbol）
    sh_market = True  # 默认沪市

    buy_costs = calc.calculate_buy_costs(entry_price, quantity, sh_market)
    sell_costs = calc.calculate_sell_costs(exit_price, quantity, sh_market)

    # 实际投入
    actual_cost = buy_costs["effective_price"] * quantity

    # 实际收入
    actual_revenue = sell_costs["effective_price"] * quantity

    # 净盈亏
    net_pnl = actual_revenue - actual_cost

    # 净收益率
    net_return_pct = net_pnl / actual_cost * 100

    # 毛收益率（不扣成本）
    gross_return_pct = (exit_price - entry_price) / entry_price * 100

    return {
        "net_pnl": net_pnl,
        "net_return_pct": net_return_pct,
        "gross_return_pct": gross_return_pct,
        "total_cost": buy_costs["total_cost"] + sell_costs["total_cost"],
        "cost_impact_pct": gross_return_pct - net_return_pct,  # 成本对收益的影响
    }