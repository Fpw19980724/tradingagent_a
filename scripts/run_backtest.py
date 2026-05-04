#!/usr/bin/env python3
"""组合级回测脚本。"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from tradingagents.signals import SignalRecorder
from tradingagents.backtesting import (
    PortfolioBacktestEngine,
    TransactionCostConfig,
    PortfolioBacktestReport,
)
from tradingagents.agent_core.types import AgentDecision, DecisionAction
from tradingagents.dataflows.a_share import get_stock_data


def parse_csv_to_df(csv_str: str) -> pd.DataFrame:
    """将get_stock_data返回的CSV字符串解析为DataFrame。"""
    lines = csv_str.strip().split('\n')
    # 跳过注释行（以#开头）
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

    # 转换数值列
    numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount', 'PctChange', 'TurnoverPct']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # 将日期设为索引
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')
        df = df.sort_index()

    return df


def load_signals_as_decisions(
    start_date: str,
    end_date: str,
    recorder: SignalRecorder,
) -> list[AgentDecision]:
    """从信号记录加载并转换为决策列表。"""
    records = recorder.load_signals(start_date=start_date, end_date=end_date)

    decisions = []
    for record in records:
        signal = record.signal
        # 只处理BUY和SELL信号
        if signal.action == DecisionAction.HOLD:
            continue

        # 获取建议数量，默认100股
        quantity = signal.suggested_quantity or 100

        decision = AgentDecision(
            agent_name=signal.metadata.get("agent_name", "tradingagents"),
            symbol=signal.symbol,
            trade_date=signal.signal_date,
            action=signal.action,
            rationale=signal.rationale,
            confidence=signal.confidence,
            quantity=quantity,
            holding_period_bars=signal.metadata.get("holding_period_bars", 5),
            metadata=signal.metadata,
        )
        decisions.append(decision)

    return decisions


def fetch_daily_data(
    symbols: list[str],
    start_date: str,
    end_date: str,
    extra_days: int = 30,
) -> dict[str, pd.DataFrame]:
    """获取所有股票的日线数据。"""
    # 扩展结束日期以覆盖持仓期
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    extended_end = (end_dt + timedelta(days=extra_days)).strftime("%Y-%m-%d")

    daily_data_map = {}

    for symbol in symbols:
        try:
            csv_str = get_stock_data(symbol, start_date, extended_end)
            df = parse_csv_to_df(csv_str)
            if not df.empty:
                daily_data_map[symbol] = df
                print(f"  {symbol}: {len(df)} 条记录")
            else:
                print(f"  {symbol}: 无数据")
        except Exception as e:
            print(f"  {symbol}: 获取失败 - {e}")

    return daily_data_map


def run_backtest(
    decisions: list[AgentDecision],
    daily_data_map: dict[str, pd.DataFrame],
    initial_capital: float,
    cost_config: TransactionCostConfig,
    max_position_pct: float,
    max_positions: int,
    buy_amount_pct: float = 0.1,
) -> PortfolioBacktestReport:
    """执行组合级回测。"""
    engine = PortfolioBacktestEngine(
        initial_capital=initial_capital,
        cost_config=cost_config,
        max_position_pct=max_position_pct,
        max_positions=max_positions,
        buy_amount_pct=buy_amount_pct,
    )

    report = engine.backtest_decisions(decisions, daily_data_map)
    return report


def print_report(report: PortfolioBacktestReport):
    """打印回测报告。"""
    print("\n" + "=" * 70)
    print("                         回测报告")
    print("=" * 70)

    print(f"\n【基本信息】")
    print(f"  回测区间: {report.start_date} ~ {report.end_date}")
    print(f"  初始资金: ¥{report.initial_capital:,.2f}")
    print(f"  最终资产: ¥{report.final_equity:,.2f}")

    print(f"\n【收益指标】")
    print(f"  总收益率:   {report.total_return:+.2f}%")
    print(f"  年化收益:   {report.annualized_return:+.2f}%")
    print(f"  年化波动:   {report.annualized_volatility:.2f}%")

    print(f"\n【风险指标】")
    print(f"  夏普比率:   {report.sharpe_ratio:.2f}")
    print(f"  索提诺比率: {report.sortino_ratio:.2f}")
    print(f"  最大回撤:   {report.max_drawdown:.2f}%")
    print(f"  回撤持续:   {report.max_drawdown_duration} 天")

    print(f"\n【交易统计】")
    print(f"  总交易次数: {report.total_trades}")
    print(f"  胜率:       {report.win_rate:.1f}%")
    print(f"  盈亏比:     {report.profit_factor:.2f}")
    print(f"  平均盈利:   {report.avg_win_pct:+.2f}%")
    print(f"  平均亏损:   {report.avg_loss_pct:+.2f}%")
    print(f"  平均持仓:   {report.avg_holding_days:.1f} 天")

    print(f"\n【交易成本】")
    print(f"  总佣金:     ¥{report.total_commission:,.2f}")
    print(f"  总印花税:   ¥{report.total_stamp_duty:,.2f}")
    print(f"  总过户费:   ¥{report.total_transfer_fee:,.2f}")
    print(f"  总成本:     ¥{report.total_costs:,.2f}")

    print("=" * 70)

    # 打印权益曲线（最近10个点）
    if report.equity_curve:
        print("\n【权益曲线（最近10天）】")
        for date, equity in report.equity_curve[-10:]:
            print(f"  {date}: ¥{equity:,.2f}")

    # 打印交易明细
    if report.trades:
        print("\n【交易明细】")
        executed_trades = [t for t in report.trades if t.executed]
        for trade in executed_trades[:20]:  # 只显示前20条
            pnl_sign = "+" if trade.return_pct >= 0 else ""
            print(f"  {trade.trade_date} {trade.symbol:8s} {trade.action:4s} "
                  f"入场¥{trade.entry_price:.2f} 出场¥{trade.exit_price:.2f} "
                  f"收益{pnl_sign}{trade.return_pct:.2f}%")
        if len(executed_trades) > 20:
            print(f"  ... 还有 {len(executed_trades) - 20} 条交易记录")


def save_report_json(report: PortfolioBacktestReport, output_path: Path):
    """保存回测报告为JSON文件。"""
    data = {
        "start_date": report.start_date,
        "end_date": report.end_date,
        "initial_capital": report.initial_capital,
        "final_equity": report.final_equity,
        "total_return": report.total_return,
        "annualized_return": report.annualized_return,
        "annualized_volatility": report.annualized_volatility,
        "sharpe_ratio": report.sharpe_ratio,
        "sortino_ratio": report.sortino_ratio,
        "max_drawdown": report.max_drawdown,
        "max_drawdown_duration": report.max_drawdown_duration,
        "total_trades": report.total_trades,
        "win_rate": report.win_rate,
        "profit_factor": report.profit_factor,
        "avg_win_pct": report.avg_win_pct,
        "avg_loss_pct": report.avg_loss_pct,
        "avg_holding_days": report.avg_holding_days,
        "total_commission": report.total_commission,
        "total_stamp_duty": report.total_stamp_duty,
        "total_transfer_fee": report.total_transfer_fee,
        "total_costs": report.total_costs,
        "equity_curve": [{"date": d, "equity": e} for d, e in report.equity_curve],
        "trades": [
            {
                "symbol": t.symbol,
                "trade_date": t.trade_date,
                "action": t.action,
                "executed": t.executed,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "return_pct": t.return_pct,
                "pnl": t.pnl,
                "notes": t.notes,
            }
            for t in report.trades
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n报告已保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="组合级回测")

    parser.add_argument(
        "--start",
        "-s",
        type=str,
        required=True,
        help="回测起始日期 YYYY-MM-DD",
    )
    parser.add_argument(
        "--end",
        "-e",
        type=str,
        required=True,
        help="回测结束日期 YYYY-MM-DD",
    )
    parser.add_argument(
        "--signals-dir",
        type=str,
        default="signals",
        help="信号存储目录",
    )
    parser.add_argument(
        "--capital",
        "-c",
        type=float,
        default=100000.0,
        help="初始资金",
    )
    parser.add_argument(
        "--max-position-pct",
        type=float,
        default=0.2,
        help="单只最大仓位比例",
    )
    parser.add_argument(
        "--max-positions",
        type=int,
        default=5,
        help="最大持仓数量",
    )
    parser.add_argument(
        "--buy-amount-pct",
        type=float,
        default=0.1,
        help="单次买入金额占总资产比例",
    )
    parser.add_argument(
        "--commission-rate",
        type=float,
        default=0.0003,
        help="佣金率",
    )
    parser.add_argument(
        "--stamp-duty-rate",
        type=float,
        default=0.0005,
        help="印花税率",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="backtest_results/report.json",
        help="报告输出路径",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("                    组合级回测系统")
    print("=" * 70)

    # 1. 配置交易成本
    cost_config = TransactionCostConfig(
        commission_rate=args.commission_rate,
        commission_min=5.0,
        stamp_duty_rate=args.stamp_duty_rate,
        transfer_fee_rate=0.0001,
    )

    print(f"\n【配置】")
    print(f"  回测区间: {args.start} ~ {args.end}")
    print(f"  初始资金: ¥{args.capital:,.2f}")
    print(f"  单只仓位上限: {args.max_position_pct * 100:.0f}%")
    print(f"  最大持仓数: {args.max_positions}")
    print(f"  佣金率: {args.commission_rate * 100:.2f}%")
    print(f"  印花税率: {args.stamp_duty_rate * 100:.2f}%")

    # 2. 加载信号
    print(f"\n【加载信号】")
    recorder = SignalRecorder(storage_dir=args.signals_dir)
    decisions = load_signals_as_decisions(args.start, args.end, recorder)

    if not decisions:
        print("  无可用信号，请先运行信号生成脚本")
        print("  python3 scripts/generate_signals.py --backfill ...")
        return

    print(f"  加载信号: {len(decisions)} 条")

    # 统计信号类型
    buy_count = sum(1 for d in decisions if d.action == DecisionAction.BUY)
    sell_count = sum(1 for d in decisions if d.action == DecisionAction.SELL)
    print(f"  BUY: {buy_count}, SELL: {sell_count}")

    # 3. 获取日线数据
    print(f"\n【获取日线数据】")
    symbols = list(set(d.symbol for d in decisions))
    print(f"  需获取: {len(symbols)} 只股票")

    daily_data_map = fetch_daily_data(symbols, args.start, args.end)

    if not daily_data_map:
        print("  无法获取任何股票数据")
        return

    print(f"  成功获取: {len(daily_data_map)} 只")

    # 4. 执行回测
    print(f"\n【执行回测】")
    report = run_backtest(
        decisions=decisions,
        daily_data_map=daily_data_map,
        initial_capital=args.capital,
        cost_config=cost_config,
        max_position_pct=args.max_position_pct,
        max_positions=args.max_positions,
        buy_amount_pct=args.buy_amount_pct,
    )

    # 5. 打印报告
    print_report(report)

    # 6. 保存报告
    save_report_json(report, Path(args.output))


if __name__ == "__main__":
    main()