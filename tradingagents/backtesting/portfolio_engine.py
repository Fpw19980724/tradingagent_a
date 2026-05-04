"""组合级回测引擎。"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from tradingagents.agent_core.types import AgentDecision, DecisionAction
from tradingagents.backtesting.costs import TransactionCostCalculator, TransactionCostConfig


@dataclass
class TradeResult:
    """单笔交易结果。"""
    symbol: str
    trade_date: str
    action: str              # BUY/SELL
    executed: bool
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: int = 0
    return_pct: float = 0.0
    pnl: float = 0.0
    holding_days: int = 0
    notes: str = ""


@dataclass
class PortfolioBacktestReport:
    """组合级回测报告。"""
    start_date: str
    end_date: str
    initial_capital: float
    final_equity: float

    # 收益指标
    total_return: float
    annualized_return: float
    annualized_volatility: float

    # 风险指标
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_duration: int

    # 交易统计
    total_trades: int
    win_rate: float
    profit_factor: float
    avg_win_pct: float
    avg_loss_pct: float
    avg_holding_days: float

    # 成本统计
    total_commission: float
    total_stamp_duty: float
    total_transfer_fee: float
    total_costs: float

    # 详细数据
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    daily_returns: list[float] = field(default_factory=list)
    trades: list[TradeResult] = field(default_factory=list)


class PortfolioBacktestEngine:
    """组合级回测引擎。"""

    def __init__(
        self,
        initial_capital: float = 100000.0,
        cost_config: TransactionCostConfig | None = None,
        max_position_pct: float = 0.2,
        max_positions: int = 5,
    ):
        self.initial_capital = initial_capital
        self.cost_config = cost_config or TransactionCostConfig()
        self.cost_calculator = TransactionCostCalculator(self.cost_config)
        self.max_position_pct = max_position_pct
        self.max_positions = max_positions

        self.cash = initial_capital
        self.positions: dict[str, dict] = {}
        self.equity_curve: list[tuple[str, float]] = []
        self.trades: list[TradeResult] = []
        self.realized_pnl: float = 0.0

        self.total_commission = 0.0
        self.total_stamp_duty = 0.0
        self.total_transfer_fee = 0.0

    def reset(self):
        """重置状态。"""
        self.cash = self.initial_capital
        self.positions.clear()
        self.equity_curve.clear()
        self.trades.clear()
        self.realized_pnl = 0.0
        self.total_commission = 0.0
        self.total_stamp_duty = 0.0
        self.total_transfer_fee = 0.0

    def get_equity(self, prices: dict[str, float]) -> float:
        """计算总资产。"""
        position_value = sum(
            self.positions[s]["quantity"] * prices.get(s, self.positions[s]["entry_price"])
            for s in self.positions
        )
        return self.cash + position_value

    def can_buy(self, symbol: str, quantity: int, price: float) -> tuple[bool, str]:
        """检查买入条件。"""
        trade_value = quantity * price
        costs = self.cost_calculator.calculate_buy_costs(price, quantity, symbol.startswith("6"))
        total_needed = trade_value + costs["total_cost"]

        if total_needed > self.cash:
            return False, f"资金不足: 需要¥{total_needed:.2f}, 可用¥{self.cash:.2f}"

        if symbol not in self.positions and len(self.positions) >= self.max_positions:
            return False, f"持仓数量已达上限: {self.max_positions}"

        equity = self.get_equity({symbol: price})
        if trade_value / equity > self.max_position_pct:
            return False, f"超过单只仓位上限: {self.max_position_pct*100}%"

        return True, ""

    def execute_buy(self, symbol: str, quantity: int, price: float, date: str) -> TradeResult | None:
        """执行买入。"""
        can_exec, reason = self.can_buy(symbol, quantity, price)
        if not can_exec:
            return TradeResult(
                symbol=symbol, trade_date=date, action="BUY",
                executed=False, notes=reason
            )

        sh_market = symbol.startswith("6")
        costs = self.cost_calculator.calculate_buy_costs(price, quantity, sh_market)

        total_cost = quantity * price + costs["total_cost"]
        self.cash -= total_cost

        self.total_commission += costs["commission"]
        self.total_transfer_fee += costs["transfer_fee"]

        if symbol in self.positions:
            old = self.positions[symbol]
            total_qty = old["quantity"] + quantity
            avg_price = (old["quantity"] * old["entry_price"] + quantity * price) / total_qty
            self.positions[symbol] = {
                "quantity": total_qty,
                "entry_price": avg_price,
                "entry_date": old["entry_date"],
            }
        else:
            self.positions[symbol] = {
                "quantity": quantity,
                "entry_price": price,
                "entry_date": date,
            }

        return TradeResult(
            symbol=symbol, trade_date=date, action="BUY",
            executed=True, entry_price=price, quantity=quantity,
            notes=f"买入{quantity}股, 成本¥{costs['total_cost']:.2f}"
        )

    def execute_sell(self, symbol: str, quantity: int | None, price: float, date: str) -> TradeResult | None:
        """执行卖出。"""
        if symbol not in self.positions:
            return TradeResult(
                symbol=symbol, trade_date=date, action="SELL",
                executed=False, notes="无持仓"
            )

        pos = self.positions[symbol]
        sell_qty = quantity or pos["quantity"]

        if sell_qty > pos["quantity"]:
            return TradeResult(
                symbol=symbol, trade_date=date, action="SELL",
                executed=False, notes=f"持仓不足: 需要{sell_qty}, 拥有{pos['quantity']}"
            )

        sh_market = symbol.startswith("6")
        costs = self.cost_calculator.calculate_sell_costs(price, sell_qty, sh_market)

        revenue = sell_qty * price - costs["total_cost"]
        self.cash += revenue

        entry_cost = sell_qty * pos["entry_price"]
        pnl = revenue - entry_cost
        pnl_pct = pnl / entry_cost * 100 if entry_cost > 0 else 0

        entry_date = datetime.strptime(pos["entry_date"], "%Y-%m-%d")
        exit_date = datetime.strptime(date, "%Y-%m-%d")
        holding_days = (exit_date - entry_date).days

        self.total_commission += costs["commission"]
        self.total_stamp_duty += costs["stamp_duty"]
        self.total_transfer_fee += costs["transfer_fee"]
        self.realized_pnl += pnl

        if sell_qty == pos["quantity"]:
            del self.positions[symbol]
        else:
            self.positions[symbol]["quantity"] -= sell_qty

        return TradeResult(
            symbol=symbol, trade_date=date, action="SELL",
            executed=True, entry_price=pos["entry_price"],
            exit_price=price, quantity=sell_qty,
            return_pct=pnl_pct, pnl=pnl, holding_days=holding_days,
            notes=f"卖出{sell_qty}股, 持仓{holding_days}天"
        )

    def process_decision(self, decision: AgentDecision, price: float) -> TradeResult:
        """处理决策。"""
        quantity = int(decision.quantity) if decision.quantity else 100

        if decision.action == DecisionAction.BUY:
            return self.execute_buy(decision.symbol, quantity, price, decision.trade_date)
        elif decision.action == DecisionAction.SELL:
            return self.execute_sell(decision.symbol, None, price, decision.trade_date)
        else:
            return TradeResult(
                symbol=decision.symbol, trade_date=decision.trade_date,
                action="HOLD", executed=False, notes="HOLD不执行"
            )

    def backtest_decisions(
        self,
        decisions: list[AgentDecision],
        daily_data_map: dict[str, pd.DataFrame],
    ) -> PortfolioBacktestReport:
        """执行回测。"""
        self.reset()

        # 按日期分组
        decisions_by_date: dict[str, list[AgentDecision]] = {}
        for d in decisions:
            if d.trade_date not in decisions_by_date:
                decisions_by_date[d.trade_date] = []
            decisions_by_date[d.trade_date].append(d)

        sorted_dates = sorted(decisions_by_date.keys())

        for trade_date in sorted_dates:
            day_decisions = decisions_by_date[trade_date]

            # 获取当日价格
            prices: dict[str, float] = {}
            for d in day_decisions:
                df = daily_data_map.get(d.symbol)
                if df is not None and not df.empty:
                    try:
                        if trade_date in df.index:
                            row = df.loc[trade_date]
                            close_col = "Close" if "Close" in df.columns else "收盘"
                            prices[d.symbol] = float(row[close_col])
                    except Exception:
                        pass

            # 执行决策
            for decision in day_decisions:
                price = prices.get(decision.symbol, 0)
                if price > 0:
                    result = self.process_decision(decision, price)
                    self.trades.append(result)

            # 记录权益
            all_prices = {}
            for symbol in self.positions:
                df = daily_data_map.get(symbol)
                if df is not None and not df.empty:
                    try:
                        if trade_date in df.index:
                            row = df.loc[trade_date]
                            close_col = "Close" if "Close" in df.columns else "收盘"
                            all_prices[symbol] = float(row[close_col])
                    except Exception:
                        all_prices[symbol] = self.positions[symbol]["entry_price"]

            equity = self.get_equity(all_prices)
            self.equity_curve.append((trade_date, equity))

        # 计算指标
        equity_values = [e for _, e in self.equity_curve]
        executed_trades = [t for t in self.trades if t.executed and t.action == "SELL"]

        total_return = (equity_values[-1] - self.initial_capital) / self.initial_capital * 100

        # 计算日收益率
        daily_returns = []
        for i in range(1, len(equity_values)):
            if equity_values[i-1] > 0:
                dr = (equity_values[i] - equity_values[i-1]) / equity_values[i-1]
                daily_returns.append(dr)

        # 年化收益
        num_days = len(equity_values)
        annual_return = ((1 + total_return/100) ** (250/num_days) - 1) * 100 if num_days > 0 else 0

        # 年化波动
        if daily_returns:
            import math
            avg_dr = sum(daily_returns) / len(daily_returns)
            variance = sum((r - avg_dr)**2 for r in daily_returns) / len(daily_returns)
            annual_vol = math.sqrt(variance) * math.sqrt(250) * 100
        else:
            annual_vol = 0

        # 夏普比率
        sharpe = (annual_return - 2) / annual_vol if annual_vol > 0 else 0

        # 最大回撤
        max_dd = 0
        peak = equity_values[0]
        for e in equity_values:
            if e > peak:
                peak = e
            dd = (peak - e) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)

        # 胜率
        wins = [t for t in executed_trades if t.return_pct > 0]
        losses = [t for t in executed_trades if t.return_pct < 0]
        win_rate = len(wins) / len(executed_trades) * 100 if executed_trades else 0

        # 盈亏比
        total_win = sum(t.return_pct for t in wins)
        total_loss = abs(sum(t.return_pct for t in losses))
        profit_factor = total_win / total_loss if total_loss > 0 else float('inf')

        avg_win = total_win / len(wins) if wins else 0
        avg_loss = total_loss / len(losses) if losses else 0

        avg_holding = sum(t.holding_days for t in executed_trades) / len(executed_trades) if executed_trades else 0

        return PortfolioBacktestReport(
            start_date=sorted_dates[0] if sorted_dates else "",
            end_date=sorted_dates[-1] if sorted_dates else "",
            initial_capital=self.initial_capital,
            final_equity=equity_values[-1] if equity_values else self.initial_capital,
            total_return=total_return,
            annualized_return=annual_return,
            annualized_volatility=annual_vol,
            sharpe_ratio=sharpe,
            sortino_ratio=sharpe,  # 简化处理
            max_drawdown=max_dd,
            max_drawdown_duration=0,  # 需要单独计算
            total_trades=len(executed_trades),
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            avg_holding_days=avg_holding,
            total_commission=self.total_commission,
            total_stamp_duty=self.total_stamp_duty,
            total_transfer_fee=self.total_transfer_fee,
            total_costs=self.total_commission + self.total_stamp_duty + self.total_transfer_fee,
            equity_curve=self.equity_curve,
            daily_returns=daily_returns,
            trades=self.trades,
        )