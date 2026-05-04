#!/usr/bin/env python
"""交易信号生成CLI脚本。"""

import argparse
from datetime import datetime
from pathlib import Path

from tradingagents.signals import SignalGenerator, SignalRecorder, load_watchlist
from tradingagents.default_config import DEFAULT_CONFIG


def main():
    parser = argparse.ArgumentParser(description="生成交易信号")

    parser.add_argument(
        "--watchlist",
        "-w",
        type=str,
        default="watchlist.csv",
        help="关注列表CSV文件路径",
    )
    parser.add_argument(
        "--date",
        "-d",
        type=str,
        default=None,
        help="交易日期 (YYYY-MM-DD)，默认今天",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="signals",
        help="信号输出目录",
    )
    parser.add_argument(
        "--backfill",
        "-b",
        action="store_true",
        help="批量生成历史信号",
    )
    parser.add_argument(
        "--start",
        "-s",
        type=str,
        default=None,
        help="历史回填起始日期",
    )
    parser.add_argument(
        "--end",
        "-e",
        type=str,
        default=None,
        help="历史回填结束日期",
    )
    parser.add_argument(
        "--provider",
        "-p",
        type=str,
        default="qwen",
        help="LLM提供商",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default="qwen3.6-plus",
        help="LLM模型",
    )
    parser.add_argument(
        "--depth",
        "-D",
        type=int,
        choices=[1, 3, 5],
        default=1,
        help="研究深度: 1=快速, 3=中等, 5=深度 (默认: 1)",
    )
    parser.add_argument(
        "--analysts",
        "-a",
        type=str,
        default="market,news,fundamentals",
        help="分析师列表，逗号分隔 (默认: market,news,fundamentals)",
    )

    args = parser.parse_args()

    # 设置日期
    if args.date is None:
        args.date = datetime.now().strftime("%Y-%m-%d")

    # 加载关注列表
    try:
        watchlist = load_watchlist(args.watchlist)
        print(f"加载关注列表: {len(watchlist)} 个股票")
    except FileNotFoundError:
        print(f"错误: 关注列表文件不存在: {args.watchlist}")
        print("请创建 watchlist.csv 文件，格式如下:")
        print("symbol,name,sector")
        print("600519,贵州茅台,白酒")
        print("000858,五粮液,白酒")
        return

    # 配置
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = args.provider
    config["deep_think_llm"] = args.model
    config["quick_think_llm"] = args.model
    config["max_debate_rounds"] = args.depth
    config["max_risk_discuss_rounds"] = args.depth

    # 解析分析师列表
    analysts = [a.strip() for a in args.analysts.split(",")]
    valid_analysts = ["market", "news", "fundamentals", "social"]
    analysts = [a for a in analysts if a in valid_analysts]
    if not analysts:
        analysts = ["market"]  # 至少保留一个
    config["selected_analysts"] = analysts

    print(f"配置: 深度={args.depth}, 分析师={analysts}")

    # 创建生成器
    generator = SignalGenerator(config=config, signal_storage_dir=args.output)
    recorder = SignalRecorder(storage_dir=args.output)

    if args.backfill:
        # 批量回填
        if not args.start or not args.end:
            print("错误: 回填模式需要指定 --start 和 --end 日期")
            return

        print(f"批量生成信号: {args.start} -> {args.end}")
        results = generator.batch_generate(args.start, args.end, watchlist)

        total = sum(len(s) for s in results.values())
        print(f"生成完成: {len(results)} 天, {total} 个信号")

        # 保存所有信号
        for date_str, signals in results.items():
            for signal in signals:
                recorder.save_signal(signal)
            print(f"  {date_str}: {len(signals)} 个信号已保存")

    else:
        # 单日生成
        print(f"生成信号: {args.date}")
        print(f"共 {len(watchlist)} 个股票，开始处理...\n")

        signals = generator.generate_and_save(watchlist, args.date)

        print(f"\n生成完成: {len(signals)} 个信号")
        for signal in signals:
            print(f"  {signal.symbol}: {signal.action.value}")

        # 显示统计
        stats = recorder.get_statistics(args.date, args.date)
        print("\n统计:")
        print(f"  BUY: {stats['by_action'].get('BUY', 0)}")
        print(f"  SELL: {stats['by_action'].get('SELL', 0)}")
        print(f"  HOLD: {stats['by_action'].get('HOLD', 0)}")


if __name__ == "__main__":
    main()