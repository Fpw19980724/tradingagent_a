"""绩效指标计算模块。"""

import math
from typing import Sequence


class PerformanceMetricsCalculator:
    """绩效指标计算器。"""

    @staticmethod
    def sharpe_ratio(
        daily_returns: Sequence[float],
        risk_free_rate: float = 0.02,
        trading_days: int = 250,
    ) -> float:
        """
        计算夏普比率。

        公式: (年化收益 - 无风险利率) / 年化波动率

        参数：
            daily_returns: 日收益率序列。
            risk_free_rate: 年化无风险利率（默认2%）。
            trading_days: 年交易日数（默认250天）。

        返回：
            float: 夏普比率。
        """
        if not daily_returns:
            return 0.0

        n = len(daily_returns)

        # 平均日收益
        avg_daily = sum(daily_returns) / n

        # 日收益标准差
        variance = sum((r - avg_daily) ** 2 for r in daily_returns) / n
        std_daily = math.sqrt(variance)

        if std_daily == 0:
            return 0.0

        # 年化收益和波动率
        annual_return = avg_daily * trading_days
        annual_volatility = std_daily * math.sqrt(trading_days)

        # 夏普比率
        sharpe = (annual_return - risk_free_rate) / annual_volatility

        return sharpe

    @staticmethod
    def max_drawdown(
        equity_curve: Sequence[float],
    ) -> tuple[float, int, int]:
        """
        计算最大回撤。

        参数：
            equity_curve: 权益曲线（总资产序列）。

        返回：
            tuple: (最大回撤百分比, 回撤起点索引, 回撤终点索引)
        """
        if not equity_curve:
            return (0.0, 0, 0)

        peak = equity_curve[0]
        peak_idx = 0
        max_dd = 0.0
        max_dd_start = 0
        max_dd_end = 0

        for i, equity in enumerate(equity_curve):
            if equity > peak:
                peak = equity
                peak_idx = i

            # 当前回撤
            if peak > 0:
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd
                    max_dd_start = peak_idx
                    max_dd_end = i

        return (max_dd * 100, max_dd_start, max_dd_end)

    @staticmethod
    def max_drawdown_duration(
        equity_curve: Sequence[float],
    ) -> int:
        """
        计算最大回撤持续天数。

        参数：
            equity_curve: 权益曲线。

        返回：
            int: 最大回撤持续天数。
        """
        if not equity_curve:
            return 0

        peak = equity_curve[0]
        max_duration = 0
        current_duration = 0

        for equity in equity_curve:
            if equity >= peak:
                peak = equity
                current_duration = 0
            else:
                current_duration += 1
                max_duration = max(max_duration, current_duration)

        return max_duration

    @staticmethod
    def annualized_return(
        total_return: float,
        num_days: int,
        trading_days: int = 250,
    ) -> float:
        """
        计算年化收益率。

        公式: (1 + 总收益)^(250/天数) - 1

        参数：
            total_return: 总收益率（百分比形式）。
            num_days: 持有天数。
            trading_days: 年交易日数。

        返回：
            float: 年化收益率（百分比形式）。
        """
        if num_days <= 0:
            return 0.0

        # 转换为小数形式
        total_return_decimal = total_return / 100

        # 年化
        annual = (1 + total_return_decimal) ** (trading_days / num_days) - 1

        return annual * 100

    @staticmethod
    def annualized_volatility(
        daily_returns: Sequence[float],
        trading_days: int = 250,
    ) -> float:
        """
        计算年化波动率。

        参数：
            daily_returns: 日收益率序列。
            trading_days: 年交易日数。

        返回：
            float: 年化波动率（百分比形式）。
        """
        if not daily_returns:
            return 0.0

        n = len(daily_returns)
        avg = sum(daily_returns) / n

        variance = sum((r - avg) ** 2 for r in daily_returns) / n
        std_daily = math.sqrt(variance)

        # 年化
        annual_vol = std_daily * math.sqrt(trading_days)

        return annual_vol * 100

    @staticmethod
    def profit_factor(
        trades: Sequence[dict],
        return_key: str = "return_pct",
    ) -> float:
        """
        计算盈亏比（Profit Factor）。

        公式: 总盈利 / 总亏损

        参数：
            trades: 交易列表，每个交易包含收益信息。
            return_key: 收益字段的键名。

        返回：
            float: 盈亏比，无亏损时返回inf。
        """
        if not trades:
            return 0.0

        gross_profit = 0.0
        gross_loss = 0.0

        for trade in trades:
            return_pct = trade.get(return_key, 0.0)
            if return_pct > 0:
                gross_profit += return_pct
            elif return_pct < 0:
                gross_loss += abs(return_pct)

        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    @staticmethod
    def win_rate(
        trades: Sequence[dict],
        return_key: str = "return_pct",
    ) -> float:
        """
        计算胜率。

        参数：
            trades: 交易列表。
            return_key: 收益字段的键名。

        返回：
            float: 胜率（百分比）。
        """
        if not trades:
            return 0.0

        wins = sum(1 for t in trades if t.get(return_key, 0.0) > 0)
        return wins / len(trades) * 100

    @staticmethod
    def avg_win_loss(
        trades: Sequence[dict],
        return_key: str = "return_pct",
    ) -> tuple[float, float]:
        """
        计算平均盈利和平均亏损。

        参数：
            trades: 交易列表。
            return_key: 收益字段的键名。

        返回：
            tuple: (平均盈利百分比, 平均亏损百分比)
        """
        if not trades:
            return (0.0, 0.0)

        wins = [t.get(return_key, 0.0) for t in trades if t.get(return_key, 0.0) > 0]
        losses = [abs(t.get(return_key, 0.0)) for t in trades if t.get(return_key, 0.0) < 0]

        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        return (avg_win, avg_loss)

    @staticmethod
    def sortino_ratio(
        daily_returns: Sequence[float],
        risk_free_rate: float = 0.02,
        trading_days: int = 250,
    ) -> float:
        """
        计算索提诺比率（只考虑下行风险）。

        参数：
            daily_returns: 日收益率序列。
            risk_free_rate: 年化无风险利率。
            trading_days: 年交易日数。

        返回：
            float: 索提诺比率。
        """
        if not daily_returns:
            return 0.0

        n = len(daily_returns)
        avg_daily = sum(daily_returns) / n

        # 只计算负收益的标准差（下行波动）
        negative_returns = [r for r in daily_returns if r < 0]
        if not negative_returns:
            return float("inf") if avg_daily > 0 else 0.0

        down_variance = sum(r ** 2 for r in negative_returns) / n
        down_std_daily = math.sqrt(down_variance)

        if down_std_daily == 0:
            return 0.0

        # 年化
        annual_return = avg_daily * trading_days
        annual_down_vol = down_std_daily * math.sqrt(trading_days)

        sortino = (annual_return - risk_free_rate) / annual_down_vol

        return sortino

    @staticmethod
    def calculate_all(
        equity_curve: Sequence[float],
        trades: Sequence[dict],
        initial_capital: float,
        return_key: str = "return_pct",
        risk_free_rate: float = 0.02,
    ) -> dict[str, float]:
        """
        计算所有绩效指标。

        参数：
            equity_curve: 权益曲线。
            trades: 交易列表。
            initial_capital: 初始资金。
            return_key: 收益字段键名。
            risk_free_rate: 无风险利率。

        返回：
            dict: 所有绩效指标。
        """
        if not equity_curve:
            return {}

        # 计算日收益率
        daily_returns = []
        for i in range(1, len(equity_curve)):
            if equity_curve[i - 1] > 0:
                dr = (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1] * 100
                daily_returns.append(dr)

        # 总收益
        final_equity = equity_curve[-1] if equity_curve else initial_capital
        total_return = (final_equity - initial_capital) / initial_capital * 100

        # 最大回撤
        max_dd, dd_start, dd_end = PerformanceMetricsCalculator.max_drawdown(equity_curve)
        dd_duration = PerformanceMetricsCalculator.max_drawdown_duration(equity_curve)

        # 年化指标
        num_days = len(equity_curve)
        annual_return = PerformanceMetricsCalculator.annualized_return(total_return, num_days)
        annual_vol = PerformanceMetricsCalculator.annualized_volatility(daily_returns)

        # 夏普比率
        sharpe = PerformanceMetricsCalculator.sharpe_ratio(daily_returns, risk_free_rate)

        # 索提诺比率
        sortino = PerformanceMetricsCalculator.sortino_ratio(daily_returns, risk_free_rate)

        # 交易统计
        executed_trades = [t for t in trades if t.get("executed", True)]
        win_rate = PerformanceMetricsCalculator.win_rate(executed_trades, return_key)
        profit_factor = PerformanceMetricsCalculator.profit_factor(executed_trades, return_key)
        avg_win, avg_loss = PerformanceMetricsCalculator.avg_win_loss(executed_trades, return_key)

        return {
            "total_return": total_return,
            "annualized_return": annual_return,
            "annualized_volatility": annual_vol,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "max_drawdown": max_dd,
            "max_drawdown_start_idx": dd_start,
            "max_drawdown_end_idx": dd_end,
            "max_drawdown_duration": dd_duration,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "total_trades": len(executed_trades),
            "winning_trades": sum(1 for t in executed_trades if t.get(return_key, 0.0) > 0),
            "losing_trades": sum(1 for t in executed_trades if t.get(return_key, 0.0) < 0),
            "final_equity": final_equity,
            "initial_capital": initial_capital,
        }