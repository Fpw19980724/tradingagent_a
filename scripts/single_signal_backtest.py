#!/usr/bin/env python3
"""单信号回测验证 - 用当前决策模拟未来持有收益。"""

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from tradingagents.agent_core.types import DecisionAction
from tradingagents.backtesting import TransactionCostCalculator, TransactionCostConfig
from tradingagents.dataflows.a_share import get_stock_data


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


def simulate_single_trade(
    symbol: str,
    action: str,
    trade_date: str,
    quantity: int,
    holding_days: int,
    df: pd.DataFrame,
    cost_config: TransactionCostConfig,
) -> dict:
    """模拟单笔交易的收益。"""
    calculator = TransactionCostCalculator(cost_config)

    # 找到入场日期（决策日之后的下一个交易日）
    trade_dt = pd.to_datetime(trade_date)

    # 找入场点
    entry_idx = None
    for i, (date, row) in enumerate(df.iterrows()):
        if date > trade_dt:
            entry_idx = i
            break

    if entry_idx is None:
        return {"error": "找不到入场日期"}

    entry_date = df.index[entry_idx]
    entry_price = df.iloc[entry_idx]['Open']  # 用开盘价入场

    # 计算入场成本
    if action == "BUY":
        costs = calculator.calculate_buy_costs(entry_price, quantity)
        total_entry_cost = costs['total_cost'] + entry_price * quantity
    else:
        # SELL需要先有持仓，这里假设已有持仓
        costs = calculator.calculate_sell_costs(entry_price, quantity)
        total_entry_value = entry_price * quantity - costs['total_cost']

    # 找出场点（持有N天后的收盘价）
    exit_idx = entry_idx + holding_days
    if exit_idx >= len(df):
        exit_idx = len(df) - 1

    exit_date = df.index[exit_idx]
    exit_price = df.iloc[exit_idx]['Close']

    # 计算出场成本/收益
    if action == "BUY":
        exit_costs = calculator.calculate_sell_costs(exit_price, quantity)
        exit_value = exit_price * quantity - exit_costs['total_cost']
        pnl = exit_value - total_entry_cost
        return_pct = (pnl / total_entry_cost) * 100
    else:
        # SELL: 假设之前买入的价格需要用户指定
        # 这里用入场价作为假设买入价
        buy_costs = calculator.calculate_buy_costs(entry_price, quantity)
        buy_total = buy_costs['total_cost'] + entry_price * quantity
        sell_value = entry_price * quantity - costs['total_cost']
        # SELL的收益是避免下跌的损失，这里计算如果继续持有的损失
        hold_value_at_exit = exit_price * quantity
        avoided_loss = entry_price * quantity - hold_value_at_exit
        pnl = avoided_loss  # 避免的损失
        return_pct = (avoided_loss / (entry_price * quantity)) * 100

    return {
        "symbol": symbol,
        "action": action,
        "entry_date": entry_date.strftime("%Y-%m-%d"),
        "entry_price": entry_price,
        "exit_date": exit_date.strftime("%Y-%m-%d"),
        "exit_price": exit_price,
        "holding_days": exit_idx - entry_idx,
        "quantity": quantity,
        "pnl": pnl,
        "return_pct": return_pct,
        "entry_costs": costs['total_cost'] if action == "BUY" else 0,
        "exit_costs": exit_costs['total_cost'] if action == "BUY" else costs['total_cost'],
    }


def simulate_sell_decision(
    symbol: str,
    trade_date: str,
    buy_price: float,  # 用户指定买入价
    quantity: int,
    holding_days: int,
    df: pd.DataFrame,
    cost_config: TransactionCostConfig,
) -> dict:
    """模拟SELL决策 - 计算避免的损失。"""
    calculator = TransactionCostCalculator(cost_config)

    trade_dt = pd.to_datetime(trade_date)

    # 找出场日期（决策日之后的下一个交易日）
    exit_idx = None
    for i, (date, row) in enumerate(df.iterrows()):
        if date > trade_dt:
            exit_idx = i
            break

    if exit_idx is None:
        return {"error": "找不到出场日期"}

    # 决策日当天卖出（假设用决策日的收盘价）
    # 或者用决策日后第一个交易日的开盘价
    exit_date = df.index[exit_idx]
    sell_price = df.iloc[exit_idx]['Open']

    # 计算卖出收益
    sell_costs = calculator.calculate_sell_costs(sell_price, quantity)
    sell_value = sell_price * quantity - sell_costs['total_cost']

    # 如果继续持有N天后的价值
    hold_idx = exit_idx + holding_days
    if hold_idx >= len(df):
        hold_idx = len(df) - 1
    hold_date = df.index[hold_idx]
    hold_price = df.iloc[hold_idx]['Close']
    hold_value = hold_price * quantity

    # 避免的损失 = 卖出价值 - 持有价值
    avoided_loss = sell_value - hold_value
    avoided_pct = (avoided_loss / (buy_price * quantity)) * 100

    # 实际收益 vs 如果继续持有
    return {
        "symbol": symbol,
        "action": "SELL",
        "sell_date": exit_date.strftime("%Y-%m-%d"),
        "sell_price": sell_price,
        "hold_date": hold_date.strftime("%Y-%m-%d"),
        "hold_price": hold_price,
        "quantity": quantity,
        "sell_value": sell_value,
        "hold_value": hold_value,
        "avoided_loss": avoided_loss,
        "avoided_pct": avoided_pct,
        "sell_costs": sell_costs['total_cost'],
    }


def main():
    parser = argparse.ArgumentParser(description="单信号回测验证")

    parser.add_argument(
        "--symbol", "-s",
        type=str,
        required=True,
        help="股票代码",
    )
    parser.add_argument(
        "--action", "-a",
        type=str,
        required=True,
        choices=["BUY", "SELL", "HOLD"],
        help="交易动作",
    )
    parser.add_argument(
        "--date", "-d",
        type=str,
        required=True,
        help="决策日期 YYYY-MM-DD",
    )
    parser.add_argument(
        "--quantity", "-q",
        type=int,
        default=100,
        help="交易数量（股）",
    )
    parser.add_argument(
        "--holding-days",
        type=int,
        default=5,
        help="持有天数",
    )
    parser.add_argument(
        "--buy-price",
        type=float,
        default=None,
        help="买入价（SELL决策时需要，计算避免的损失）",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=30,
        help="获取历史数据天数",
    )
    parser.add_argument(
        "--lookforward",
        type=int,
        default=20,
        help="获取未来数据天数（用于模拟）",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("           单信号回测验证")
    print("=" * 60)

    if args.action == "HOLD":
        print("\nHOLD决策无需回测模拟")
        return

    # 配置交易成本
    cost_config = TransactionCostConfig(
        commission_rate=0.0003,
        commission_min=5.0,
        stamp_duty_rate=0.0005,
        transfer_fee_rate=0.0001,
    )

    print(f"\n【决策信息】")
    print(f"  股票: {args.symbol}")
    print(f"  动作: {args.action}")
    print(f"  决策日: {args.date}")
    print(f"  数量: {args.quantity}股")
    print(f"  持有天数: {args.holding_days}天")

    # 计算数据获取范围
    trade_dt = datetime.strptime(args.date, "%Y-%m-%d")
    start_dt = trade_dt - timedelta(days=args.lookback)
    end_dt = trade_dt + timedelta(days=args.lookforward + args.holding_days)

    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    print(f"\n【获取数据】")
    print(f"  范围: {start_date} ~ {end_date}")

    # 获取行情数据
    try:
        csv_str = get_stock_data(args.symbol, start_date, end_date)
        df = parse_csv_to_df(csv_str)

        if df.empty:
            print("  无法获取数据")
            return

        print(f"  获取成功: {len(df)}条记录")
    except Exception as e:
        print(f"  获取失败: {e}")
        return

    # 执行模拟
    print(f"\n【模拟交易】")

    if args.action == "BUY":
        result = simulate_single_trade(
            symbol=args.symbol,
            action="BUY",
            trade_date=args.date,
            quantity=args.quantity,
            holding_days=args.holding_days,
            df=df,
            cost_config=cost_config,
        )

        if "error" in result:
            print(f"  {result['error']}")
            return

        print(f"  入场日期: {result['entry_date']}")
        print(f"  入场价格: ¥{result['entry_price']:.2f}")
        print(f"  出场日期: {result['exit_date']}")
        print(f"  出场价格: ¥{result['exit_price']:.2f}")
        print(f"  实际持有: {result['holding_days']}天")
        print(f"  入场成本: ¥{result['entry_costs']:.2f}")
        print(f"  出场成本: ¥{result['exit_costs']:.2f}")

        pnl_sign = "+" if result['pnl'] >= 0 else ""
        print(f"\n【模拟收益】")
        print(f"  盈亏: {pnl_sign}¥{result['pnl']:.2f}")
        print(f"  收益率: {pnl_sign}{result['return_pct']:.2f}%")

    elif args.action == "SELL":
        if args.buy_price is None:
            print("  SELL决策需要指定买入价 (--buy-price)")
            print("  用于计算避免的损失")
            return

        result = simulate_sell_decision(
            symbol=args.symbol,
            trade_date=args.date,
            buy_price=args.buy_price,
            quantity=args.quantity,
            holding_days=args.holding_days,
            df=df,
            cost_config=cost_config,
        )

        if "error" in result:
            print(f"  {result['error']}")
            return

        print(f"  卖出日期: {result['sell_date']}")
        print(f"  卖出价格: ¥{result['sell_price']:.2f}")
        print(f"  卖出价值: ¥{result['sell_value']:.2f}")
        print(f"  卖出成本: ¥{result['sell_costs']:.2f}")

        print(f"\n【如果继续持有{args.holding_days}天】")
        print(f"  持有日期: {result['hold_date']}")
        print(f"  持有价格: ¥{result['hold_price']:.2f}")
        print(f"  持有价值: ¥{result['hold_value']:.2f}")

        avoided_sign = "+" if result['avoided_loss'] >= 0 else ""
        print(f"\n【避免的损失】")
        print(f"  避免损失: {avoided_sign}¥{result['avoided_loss']:.2f}")
        print(f"  避免比例: {avoided_sign}{result['avoided_pct']:.2f}%")

        if result['avoided_loss'] > 0:
            print(f"\n  ✅ SELL决策正确！避免了¥{result['avoided_loss']:.2f}损失")
        else:
            print(f"\n  ❌ SELL决策过早卖出，错失¥{-result['avoided_loss']:.2f}收益")

    print("=" * 60)


if __name__ == "__main__":
    main()