import pandas as pd

from tradingagents.agent_core.base import BaseAgent
from tradingagents.agent_core.types import AgentDecision, AgentExecutionContext, AgentRunRequest, DecisionAction
from tradingagents.backtesting.costs import TransactionCostCalculator, TransactionCostConfig, calculate_net_return
from tradingagents.backtesting.types import BacktestReport, BacktestTradeResult


class BacktestEngine:
    """基于本地市场数据工具执行标准化回测。"""

    def __init__(self, market_tools):
        """
        初始化回测引擎。

        参数：
            market_tools: 市场数据工具箱实例。

        返回：
            None: 无返回值。
        """
        self.market_tools = market_tools

    def backtest_decision(self, decision: AgentDecision, bar_rule: str = "1min") -> BacktestTradeResult:
        """
        回测单个 Agent 决策。

        参数：
            decision: 标准化 Agent 决策。
            bar_rule: K 线重采样规则。

        返回：
            BacktestTradeResult: 单笔回测结果。
        """
        if decision.action == DecisionAction.HOLD:
            return BacktestTradeResult(
                agent_name=decision.agent_name,
                symbol=decision.symbol,
                trade_date=decision.trade_date,
                action=decision.action.value,
                executed=False,
                notes="HOLD 决策不执行交易。",
            )

        bars = self.market_tools.build_bars(decision.symbol, decision.trade_date, rule=bar_rule)
        if bars.empty:
            return BacktestTradeResult(
                agent_name=decision.agent_name,
                symbol=decision.symbol,
                trade_date=decision.trade_date,
                action=decision.action.value,
                executed=False,
                notes="缺少可用 K 线数据。",
            )

        entry_index = self._resolve_entry_index(bars, decision.decision_time)
        exit_index = min(entry_index + max(decision.holding_period_bars, 1), len(bars) - 1)

        entry_price = float(bars.iloc[entry_index]["open"])
        exit_price = float(bars.iloc[exit_index]["close"])
        direction = 1 if decision.action == DecisionAction.BUY else -1
        return_pct = ((exit_price - entry_price) / entry_price) * direction
        pnl = return_pct * decision.quantity

        return BacktestTradeResult(
            agent_name=decision.agent_name,
            symbol=decision.symbol,
            trade_date=decision.trade_date,
            action=decision.action.value,
            executed=True,
            entry_price=entry_price,
            exit_price=exit_price,
            return_pct=return_pct,
            pnl=pnl,
        )

    def backtest_many(
        self,
        decisions: list[AgentDecision],
        bar_rule: str = "1min",
    ) -> BacktestReport:
        """
        批量回测多个 Agent 决策。

        参数：
            decisions: 标准化 Agent 决策列表。
            bar_rule: K 线重采样规则。

        返回：
            BacktestReport: 汇总回测结果。
        """
        trades = [self.backtest_decision(decision, bar_rule=bar_rule) for decision in decisions]
        executed = [trade for trade in trades if trade.executed]
        cumulative_return = sum(trade.return_pct for trade in executed)
        average_return = cumulative_return / len(executed) if executed else 0.0
        win_rate = (
            len([trade for trade in executed if trade.return_pct > 0]) / len(executed)
            if executed
            else 0.0
        )
        agent_name = decisions[0].agent_name if decisions else ""
        return BacktestReport(
            agent_name=agent_name,
            total_decisions=len(decisions),
            executed_trades=len(executed),
            cumulative_return=cumulative_return,
            average_return=average_return,
            win_rate=win_rate,
            trades=trades,
        )

    def backtest_agent(
        self,
        agent: BaseAgent,
        requests: list[AgentRunRequest],
        context: AgentExecutionContext,
        bar_rule: str = "1min",
    ) -> BacktestReport:
        """
        让 Agent 先独立运行，再对其输出决策执行回测。

        参数：
            agent: 目标 Agent 实例。
            requests: Agent 运行请求列表。
            context: Agent 运行上下文。
            bar_rule: K 线重采样规则。

        返回：
            BacktestReport: 汇总回测结果。
        """
        decisions: list[AgentDecision] = []
        for request in requests:
            result = agent.run(request, context)
            if result.decision is not None:
                decisions.append(result.decision)
        return self.backtest_many(decisions, bar_rule=bar_rule)

    def _resolve_entry_index(self, bars: pd.DataFrame, decision_time: str | None) -> int:
        """
        根据决策时间确定入场 K 线索引。

        参数：
            bars: K 线数据表。
            decision_time: 决策时间，格式兼容 pandas 时间解析。

        返回：
            int: 入场索引。
        """
        if decision_time is None:
            return 0

        timestamp = pd.Timestamp(decision_time)
        matched = bars[bars["timestamp"] >= timestamp]
        if matched.empty:
            return len(bars) - 1
        return int(matched.index[0])

    # ==================== 日线数据回测方法 ====================

    def backtest_decision_daily(
        self,
        decision: AgentDecision,
        daily_data: pd.DataFrame,
        cost_config: TransactionCostConfig | None = None,
        holding_days: int = 5,
    ) -> BacktestTradeResult:
        """
        使用日线数据回测单个决策。

        参数：
            decision: Agent决策。
            daily_data: 日线OHLCV数据（需包含日期列或索引）。
            cost_config: 交易成本配置。
            holding_days: 默认持仓天数。

        返回：
            BacktestTradeResult: 回测结果。
        """
        if decision.action == DecisionAction.HOLD:
            return BacktestTradeResult(
                agent_name=decision.agent_name,
                symbol=decision.symbol,
                trade_date=decision.trade_date,
                action=decision.action.value,
                executed=False,
                notes="HOLD 决策不执行交易。",
            )

        if daily_data.empty:
            return BacktestTradeResult(
                agent_name=decision.agent_name,
                symbol=decision.symbol,
                trade_date=decision.trade_date,
                action=decision.action.value,
                executed=False,
                notes="缺少日线数据。",
            )

        # 确保日期索引
        if "日期" in daily_data.columns:
            daily_data = daily_data.set_index("日期")
        elif "date" in daily_data.columns:
            daily_data = daily_data.set_index("date")

        # 查找决策日期对应的索引
        try:
            trade_date_idx = daily_data.index.get_loc(decision.trade_date)
        except KeyError:
            # 决策日期不在数据中，使用最接近的日期
            return BacktestTradeResult(
                agent_name=decision.agent_name,
                symbol=decision.symbol,
                trade_date=decision.trade_date,
                action=decision.action.value,
                executed=False,
                notes=f"决策日期 {decision.trade_date} 不在日线数据范围内。",
            )

        # 入场：决策后下一个交易日的开盘价
        entry_idx = trade_date_idx + 1
        if entry_idx >= len(daily_data):
            return BacktestTradeResult(
                agent_name=decision.agent_name,
                symbol=decision.symbol,
                trade_date=decision.trade_date,
                action=decision.action.value,
                executed=False,
                notes="决策日期后无足够交易日执行。",
            )

        # 出场：持仓期后的收盘价
        actual_holding = decision.holding_period_bars if decision.holding_period_bars > 0 else holding_days
        exit_idx = min(entry_idx + actual_holding, len(daily_data) - 1)

        entry_price = float(daily_data.iloc[entry_idx]["open"] if "open" in daily_data.columns else daily_data.iloc[entry_idx]["开盘"])
        exit_price = float(daily_data.iloc[exit_idx]["close"] if "close" in daily_data.columns else daily_data.iloc[exit_idx]["收盘"])

        # 计算毛收益
        direction = 1 if decision.action == DecisionAction.BUY else -1
        gross_return_pct = ((exit_price - entry_price) / entry_price) * direction * 100

        # 计算净收益（扣除成本）
        quantity = int(decision.quantity) if decision.quantity else 100
        sh_market = decision.symbol.startswith("6")

        if cost_config:
            net_result = calculate_net_return(entry_price, exit_price, quantity, cost_config)
            net_return_pct = net_result["net_return_pct"]
            total_cost = net_result["total_cost"]
        else:
            net_return_pct = gross_return_pct
            total_cost = 0.0

        pnl = net_return_pct * quantity / 100 * entry_price

        return BacktestTradeResult(
            agent_name=decision.agent_name,
            symbol=decision.symbol,
            trade_date=decision.trade_date,
            action=decision.action.value,
            executed=True,
            entry_price=entry_price,
            exit_price=exit_price,
            return_pct=net_return_pct,
            pnl=pnl,
            notes=f"持仓{actual_holding}天, 成本{total_cost:.2f}元",
        )

    def backtest_many_daily(
        self,
        decisions: list[AgentDecision],
        daily_data_map: dict[str, pd.DataFrame],
        cost_config: TransactionCostConfig | None = None,
        holding_days: int = 5,
    ) -> BacktestReport:
        """
        使用日线数据批量回测决策。

        参数：
            decisions: 决策列表。
            daily_data_map: 股票代码到日线数据的映射。
            cost_config: 交易成本配置。
            holding_days: 默认持仓天数。

        返回：
            BacktestReport: 汇总结果。
        """
        trades: list[BacktestTradeResult] = []

        for decision in decisions:
            daily_data = daily_data_map.get(decision.symbol)
            if daily_data is None:
                trades.append(BacktestTradeResult(
                    agent_name=decision.agent_name,
                    symbol=decision.symbol,
                    trade_date=decision.trade_date,
                    action=decision.action.value,
                    executed=False,
                    notes="缺少该股票日线数据。",
                ))
                continue

            result = self.backtest_decision_daily(
                decision, daily_data, cost_config, holding_days
            )
            trades.append(result)

        executed = [t for t in trades if t.executed]
        cumulative_return = sum(t.return_pct for t in executed)
        average_return = cumulative_return / len(executed) if executed else 0.0
        win_rate = len([t for t in executed if t.return_pct > 0]) / len(executed) if executed else 0.0

        agent_name = decisions[0].agent_name if decisions else ""

        return BacktestReport(
            agent_name=agent_name,
            total_decisions=len(decisions),
            executed_trades=len(executed),
            cumulative_return=cumulative_return,
            average_return=average_return,
            win_rate=win_rate,
            trades=trades,
        )
