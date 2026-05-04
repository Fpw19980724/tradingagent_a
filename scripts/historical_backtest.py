#!/usr/bin/env python3
"""严格历史回测 - 不看未来数据，真实模拟历史交易。"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from tradingagents.agent_core.types import AgentDecision, DecisionAction
from tradingagents.backtesting import TransactionCostCalculator, TransactionCostConfig
from tradingagents.signals import SignalRecorder


def parse_csv_to_df(csv_str: str) -> pd.DataFrame:
    """将get_stock_data返回的CSV字符串解析为DataFrame。"""
    lines = csv_str.strip().split('\n')
    data_lines = [l for l in lines if l and not l.startswith('#')]
    if not data_lines:
        return pd.DataFrame()

    header = data_lines[0].split(',')
    data = []
    for line in data_lines[1:]:
        if line:
            row = line.split(',')
            if len(row) == len(header):
                data.append(row)

    df = pd.DataFrame(data, columns=header)

    numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount', 'PctChange', 'TurnoverPct']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')
        df = df.sort_index()

    return df


@dataclass
class HistoricalTrade:
    """历史交易记录。"""
    decision_date: str        # 决策日（只用到这天为止的数据）
    symbol: str
    action: str
    entry_date: str           # 实际入场日（决策日后第一个交易日）
    entry_price: float        # 入场价（开盘价，真实可执行）
    exit_date: str            # 出场日
    exit_price: float         # 出场价（收盘价）
    quantity: int
    holding_days: int         # 实际持有天数
    pnl: float
    return_pct: float
    commission: float
    stamp_duty: float
    transfer_fee: float
    total_cost: float
    executed: bool
    notes: str = ""


class StrictHistoricalBacktest:
    """严格历史回测引擎 - 不看未来数据。"""

    def __init__(
        self,
        initial_capital: float = 100000.0,
        cost_config: TransactionCostConfig = None,
        max_position_pct: float = 0.2,
        max_positions: int = 5,
    ):
        self.initial_capital = initial_capital
        self.cost_config = cost_config or TransactionCostConfig()
        self.cost_calculator = TransactionCostCalculator(self.cost_config)
        self.max_position_pct = max_position_pct
        self.max_positions = max_positions

        self.cash = initial_capital
        self.positions: dict[str, dict] = {}  # symbol -> {quantity, entry_price, entry_date}
        self.equity_curve: list[tuple[str, float]] = []
        self.trades: list[HistoricalTrade] = []
        self.realized_pnl = 0.0

        # 成本统计
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

    def find_trade_dates(
        self,
        df: pd.DataFrame,
        decision_date: str,
        holding_period: int,
    ) -> tuple[str, str, float, float]:
        """
        找到入场和出场日期及价格。

        关键：只用决策日之前的数据做决策，
        入场用决策日后第一个交易日的开盘价（真实可执行）。

        返回：(entry_date, exit_date, entry_price, exit_price)
        """
        decision_dt = pd.to_datetime(decision_date)

        # 找入场日：决策日后第一个交易日
        entry_idx = None
        for i, (date, row) in enumerate(df.iterrows()):
            if date > decision_dt:
                entry_idx = i
                break

        if entry_idx is None:
            return None, None, None, None  # 找不到入场日

        entry_date = df.index[entry_idx]
        entry_price = df.iloc[entry_idx]['Open']  # 开盘价入场（真实可执行）

        # 找出场日：持有N天后
        exit_idx = entry_idx + holding_period
        if exit_idx >= len(df):
            exit_idx = len(df) - 1

        exit_date = df.index[exit_idx]
        exit_price = df.iloc[exit_idx]['Close']  # 收盘价出场

        actual_holding = exit_idx - entry_idx

        return (
            entry_date.strftime("%Y-%m-%d"),
            exit_date.strftime("%Y-%m-%d"),
            entry_price,
            exit_price,
            actual_holding,
        )

    def execute_buy(
        self,
        symbol: str,
        decision_date: str,
        entry_date: str,
        entry_price: float,
        quantity: int,
    ) -> HistoricalTrade:
        """执行买入。"""
        # 检查仓位限制
        position_value = entry_price * quantity
        total_equity = self.cash + sum(
            p['quantity'] * p['entry_price'] for p in self.positions.values()
        )

        # 检查单只仓位上限
        if position_value > total_equity * self.max_position_pct:
            quantity = int(total_equity * self.max_position_pct / entry_price)
            if quantity < 1:
                return HistoricalTrade(
                    decision_date=decision_date,
                    symbol=symbol,
                    action="BUY",
                    executed=False,
                    notes="超出单只仓位上限",
                )

        # 检查持仓数量上限
        if symbol not in self.positions and len(self.positions) >= self.max_positions:
            return HistoricalTrade(
                decision_date=decision_date,
                symbol=symbol,
                action="BUY",
                executed=False,
                notes="超出持仓数量上限",
            )

        # 检查资金
        costs = self.cost_calculator.calculate_buy_costs(entry_price, quantity)
        total_cost = entry_price * quantity + costs['total_cost']

        if total_cost > self.cash:
            # 资金不足，调整数量
            max_quantity = int((self.cash - costs['commission_min']) / entry_price)
            if max_quantity < 1:
                return HistoricalTrade(
                    decision_date=decision_date,
                    symbol=symbol,
                    action="BUY",
                    executed=False,
                    notes="资金不足",
                )
            quantity = max_quantity
            costs = self.cost_calculator.calculate_buy_costs(entry_price, quantity)
            total_cost = entry_price * quantity + costs['total_cost']

        # 执行买入
        self.cash -= total_cost
        self.positions[symbol] = {
            'quantity': quantity,
            'entry_price': entry_price,
            'entry_date': entry_date,
        }

        self.total_commission += costs['commission']
        self.total_transfer_fee += costs['transfer_fee']

        return HistoricalTrade(
            decision_date=decision_date,
            symbol=symbol,
            action="BUY",
            entry_date=entry_date,
            entry_price=entry_price,
            quantity=quantity,
            executed=True,
            commission=costs['commission'],
            transfer_fee=costs['transfer_fee'],
            total_cost=costs['total_cost'],
        )

    def execute_sell(
        self,
        symbol: str,
        decision_date: str,
        exit_date: str,
        exit_price: float,
    ) -> HistoricalTrade:
        """执行卖出。"""
        if symbol not in self.positions:
            return HistoricalTrade(
                decision_date=decision_date,
                symbol=symbol,
                action="SELL",
                executed=False,
                notes="无持仓",
            )

        pos = self.positions[symbol]
        quantity = pos['quantity']
        entry_price = pos['entry_price']
        entry_date = pos['entry_date']

        # 计算卖出收入
        costs = self.cost_calculator.calculate_sell_costs(exit_price, quantity)
        sell_value = exit_price * quantity - costs['total_cost']

        # 计算盈亏
        buy_cost = entry_price * quantity  # 原始买入成本（不含费用）
        pnl = sell_value - buy_cost
        return_pct = (pnl / buy_cost) * 100

        # 更新状态
        self.cash += sell_value
        del self.positions[symbol]
        self.realized_pnl += pnl

        self.total_commission += costs['commission']
        self.total_stamp_duty += costs['stamp_duty']
        self.total_transfer_fee += costs['transfer_fee']

        return HistoricalTrade(
            decision_date=decision_date,
            symbol=symbol,
            action="SELL",
            entry_date=entry_date,
            entry_price=entry_price,
            exit_date=exit_date,
            exit_price=exit_price,
            quantity=quantity,
            pnl=pnl,
            return_pct=return_pct,
            commission=costs['commission'],
            stamp_duty=costs['stamp_duty'],
            transfer_fee=costs['transfer_fee'],
            total_cost=costs['total_cost'],
            executed=True,
        )

    def backtest_decision(
        self,
        decision: AgentDecision,
        df: pd.DataFrame,
    ) -> HistoricalTrade:
        """
        回测单个决策。

        关键：决策只基于decision_date之前的数据，
        入场是decision_date后第一个交易日。
        """
        if decision.action == DecisionAction.HOLD:
            return HistoricalTrade(
                decision_date=decision.trade_date,
                symbol=decision.symbol,
                action="HOLD",
                executed=False,
                notes="HOLD无操作",
            )

        # 找入场/出场日期
        holding_period = int(decision.holding_period_bars) if decision.holding_period_bars else 5

        result = self.find_trade_dates(df, decision.trade_date, holding_period)
        entry_date, exit_date, entry_price, exit_price, actual_holding = result

        if entry_date is None:
            return HistoricalTrade(
                decision_date=decision.trade_date,
                symbol=decision.symbol,
                action=decision.action.value,
                executed=False,
                notes="找不到入场日",
            )

        quantity = int(decision.quantity) if decision.quantity else 100

        if decision.action == DecisionAction.BUY:
            trade = self.execute_buy(
                symbol=decision.symbol,
                decision_date=decision.trade_date,
                entry_date=entry_date,
                entry_price=entry_price,
                quantity=quantity,
            )
        else:  # SELL
            trade = self.execute_sell(
                symbol=decision.symbol,
                decision_date=decision.trade_date,
                exit_date=exit_date,
                exit_price=exit_price,
            )

        # 更新出场信息（BUY需要）
        if decision.action == DecisionAction.BUY and trade.executed:
            trade.exit_date = exit_date
            trade.exit_price = exit_price
            trade.holding_days = actual_holding

            # 计算收益（需要卖出才能算）
            # 这里先记录，后面按出场日卖出
            # 实际回测中，买入后会在持有期结束时自动卖出

        return trade


def load_signals(signals_dir: str, start_date: str, end_date: str) -> list[AgentDecision]:
    """从信号目录加载决策。"""
    recorder = SignalRecorder(storage_dir=signals_dir)
    records = recorder.load_signals(start_date=start_date, end_date=end_date)

    decisions = []
    for record in records:
        signal = record.signal
        if signal.action == DecisionAction.HOLD:
            continue

        decision = AgentDecision(
            agent_name=signal.metadata.get("agent_name", "tradingagents"),
            symbol=signal.symbol,
            trade_date=signal.signal_date,
            action=signal.action,
            rationale=signal.rationale,
            confidence=signal.confidence,
            quantity=signal.suggested_quantity or 100,
            holding_period_bars=signal.metadata.get("holding_period_bars", 5),
            metadata=signal.metadata,
        )
        decisions.append(decision)

    return decisions


def fetch_daily_data(
    symbols: list[str],
    start_date: str,
    end_date: str,
    extra_days: int = 20,
) -> dict[str, pd.DataFrame]:
    """获取日线数据（需要额外天数用于持有期）。"""
    from tradingagents.dataflows.a_share import get_stock_data

    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    extended_end = (end_dt + timedelta(days=extra_days)).strftime("%Y-%m-%d")

    daily_data = {}
    for symbol in symbols:
        try:
            csv_str = get_stock_data(symbol, start_date, extended_end)
            df = parse_csv_to_df(csv_str)
            if not df.empty:
                daily_data[symbol] = df
        except Exception:
            pass

    return daily_data


def generate_report(
    engine: StrictHistoricalBacktest,
    start_date: str,
    end_date: str,
) -> dict:
    """生成回测报告。"""
    # 计算权益曲线
    equity_curve = engine.equity_curve

    # 计算收益指标
    if len(equity_curve) > 1:
        values = [e for _, e in equity_curve]
        total_return = (values[-1] - engine.initial_capital) / engine.initial_capital * 100

        # 日收益率
        daily_returns = []
        for i in range(1, len(values)):
            daily_returns.append((values[i] - values[i-1]) / values[i-1])

        # 年化波动率
        if len(daily_returns) > 1:
            annualized_volatility = pd.Series(daily_returns).std() * 252 * 100
        else:
            annualized_volatility = 0.0

        # 夏普比率（假设无风险收益2%）
        if annualized_volatility > 0:
            annualized_return = total_return * 252 / len(values)
            sharpe_ratio = (annualized_return - 2) / annualized_volatility
        else:
            sharpe_ratio = 0.0

        # 最大回撤
        peak = values[0]
        max_dd = 0.0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd
    else:
        total_return = 0.0
        annualized_volatility = 0.0
        sharpe_ratio = 0.0
        max_dd = 0.0

    # 交易统计
    executed_trades = [t for t in engine.trades if t.executed]
    total_trades = len(executed_trades)

    if total_trades > 0:
        wins = [t for t in executed_trades if t.pnl > 0]
        losses = [t for t in executed_trades if t.pnl <= 0]
        win_rate = len(wins) / total_trades * 100

        avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0
        avg_win_pct = sum(t.return_pct for t in wins) / len(wins) if wins else 0
        avg_loss_pct = sum(t.return_pct for t in losses) / len(losses) if losses else 0

        profit_factor = abs(sum(t.pnl for t in wins) / sum(t.pnl for t in losses)) if losses and sum(t.pnl for t in losses) != 0 else 0

        avg_holding = sum(t.holding_days for t in executed_trades if t.holding_days) / total_trades
    else:
        win_rate = 0.0
        avg_win_pct = 0.0
        avg_loss_pct = 0.0
        profit_factor = 0.0
        avg_holding = 0.0

    return {
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": engine.initial_capital,
        "final_equity": engine.cash + sum(
            p['quantity'] * p['entry_price'] for p in engine.positions.values()
        ) if engine.positions else engine.cash,
        "total_return": total_return,
        "annualized_volatility": annualized_volatility,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_dd,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "avg_holding_days": avg_holding,
        "total_commission": engine.total_commission,
        "total_stamp_duty": engine.total_stamp_duty,
        "total_transfer_fee": engine.total_transfer_fee,
        "total_costs": engine.total_commission + engine.total_stamp_duty + engine.total_transfer_fee,
        "trades": executed_trades,
    }


def print_report(report: dict):
    """打印回测报告。"""
    print("\n" + "=" * 70)
    print("                    严格历史回测报告")
    print("=" * 70)

    print(f"\n【回测原则】")
    print(f"  ✅ 决策只基于决策日之前的数据")
    print(f"  ✅ 入场用决策日后第一个交易日开盘价（真实可执行）")
    print(f"  ✅ 出场用持有期后收盘价")

    print(f"\n【基本信息】")
    print(f"  回测区间: {report['start_date']} ~ {report['end_date']}")
    print(f"  初始资金: ¥{report['initial_capital']:,.2f}")
    print(f"  最终资产: ¥{report['final_equity']:,.2f}")

    print(f"\n【收益指标】")
    pnl_sign = "+" if report['total_return'] >= 0 else ""
    print(f"  总收益率: {pnl_sign}{report['total_return']:.2f}%")
    print(f"  年化波动: {report['annualized_volatility']:.2f}%")
    print(f"  夏普比率: {report['sharpe_ratio']:.2f}")
    print(f"  最大回撤: {report['max_drawdown']:.2f}%")

    print(f"\n【交易统计】")
    print(f"  总交易次数: {report['total_trades']}")
    print(f"  胜率: {report['win_rate']:.1f}%")
    print(f"  盈亏比: {report['profit_factor']:.2f}")
    print(f"  平均盈利: +{report['avg_win_pct']:.2f}%")
    print(f"  平均亏损: {report['avg_loss_pct']:.2f}%")
    print(f"  平均持仓: {report['avg_holding_days']:.1f}天")

    print(f"\n【交易成本】")
    print(f"  佣金: ¥{report['total_commission']:,.2f}")
    print(f"  印花税: ¥{report['total_stamp_duty']:,.2f}")
    print(f"  过户费: ¥{report['total_transfer_fee']:,.2f}")
    print(f"  总成本: ¥{report['total_costs']:,.2f}")

    # 打印交易明细
    if report['trades']:
        print(f"\n【交易明细】")
        for trade in report['trades'][:20]:
            pnl_s = "+" if trade.pnl >= 0 else ""
            print(f"  {trade.decision_date} {trade.symbol:8s} {trade.action:4s} "
                  f"入¥{trade.entry_price:.2f} 出¥{trade.exit_price:.2f} "
                  f"{pnl_s}{trade.return_pct:.2f}%")

        if len(report['trades']) > 20:
            print(f"  ... 还有 {len(report['trades']) - 20} 条")

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="严格历史回测")

    parser.add_argument("--signals-dir", type=str, default="signals", help="信号目录")
    parser.add_argument("--start", "-s", type=str, required=True, help="起始日期")
    parser.add_argument("--end", "-e", type=str, required=True, help="结束日期")
    parser.add_argument("--capital", "-c", type=float, default=100000.0, help="初始资金")
    parser.add_argument("--max-position-pct", type=float, default=0.2, help="单只仓位上限")
    parser.add_argument("--max-positions", type=int, default=5, help="最大持仓数")
    parser.add_argument("--output", "-o", type=str, default="backtest_results/historical.json", help="输出路径")

    args = parser.parse_args()

    print("=" * 70)
    print("                    严格历史回测系统")
    print("=" * 70)

    # 加载信号
    print(f"\n【加载历史信号】")
    decisions = load_signals(args.signals_dir, args.start, args.end)

    if not decisions:
        print("  无历史信号，请先生成:")
        print("  python3 scripts/generate_signals.py --backfill --start ... --end ...")
        return

    print(f"  加载: {len(decisions)} 条决策")
    buy_count = sum(1 for d in decisions if d.action == DecisionAction.BUY)
    sell_count = sum(1 for d in decisions if d.action == DecisionAction.SELL)
    print(f"  BUY: {buy_count}, SELL: {sell_count}")

    # 获取数据
    print(f"\n【获取日线数据】")
    symbols = list(set(d.symbol for d in decisions))
    daily_data = fetch_daily_data(symbols, args.start, args.end)

    print(f"  成功: {len(daily_data)}/{len(symbols)} 只")

    # 执行回测
    print(f"\n【执行回测】")
    engine = StrictHistoricalBacktest(
        initial_capital=args.capital,
        max_position_pct=args.max_position_pct,
        max_positions=args.max_positions,
    )

    # 按日期排序执行
    decisions.sort(key=lambda d: d.trade_date)

    for decision in decisions:
        if decision.symbol not in daily_data:
            continue

        df = daily_data[decision.symbol]
        trade = engine.backtest_decision(decision, df)

        # 记录每日权益
        equity = engine.cash + sum(
            p['quantity'] * p['entry_price'] for p in engine.positions.values()
        )
        engine.equity_curve.append((decision.trade_date, equity))

    # 生成报告
    report = generate_report(engine, args.start, args.end)
    print_report(report)

    # 保存报告
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 转换trades为可序列化格式
    report_copy = report.copy()
    report_copy['trades'] = [
        {
            'decision_date': t.decision_date,
            'symbol': t.symbol,
            'action': t.action,
            'entry_date': t.entry_date,
            'entry_price': t.entry_price,
            'exit_date': t.exit_date,
            'exit_price': t.exit_price,
            'quantity': t.quantity,
            'pnl': t.pnl,
            'return_pct': t.return_pct,
            'executed': t.executed,
        }
        for t in report['trades']
    ]

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report_copy, f, ensure_ascii=False, indent=2)

    print(f"\n报告已保存: {output_path}")


if __name__ == "__main__":
    main()