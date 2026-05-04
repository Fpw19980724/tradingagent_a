#!/usr/bin/env python3
"""测试智能分析功能。"""

import sys
from pathlib import Path

# 确保项目根目录在Python路径中
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime
from tradingagents.data_cache import get_db, get_fetcher
from tradingagents.signals import SignalGenerator


def test_database():
    """测试数据库基本功能。"""
    print("\n=== 测试数据库 ===")
    db = get_db("test_cache.db")

    # 测试保存新闻
    news_list = [
        {
            'title': '测试新闻标题',
            'source': '测试来源',
            'publish_time': '2026-05-03 10:00:00',
            'content': '测试内容',
            'url': 'http://test.com',
        }
    ]
    count = db.save_news('600400', news_list)
    print(f"保存新闻: {count} 条新增")

    # 测试获取最新新闻时间
    latest = db.get_latest_news_time('600400')
    print(f"最新新闻时间: {latest}")

    # 测试统计
    stats = db.get_statistics()
    print(f"统计: {stats}")

    db.close()
    print("数据库测试完成")


def test_fetcher():
    """测试数据获取器。"""
    print("\n=== 测试数据获取器 ===")
    fetcher = get_fetcher("test_cache.db")

    # 测试获取季度日期
    quarter_date = fetcher._get_latest_quarter_date("2026-05-03")
    print(f"最近季度日期: {quarter_date}")

    print("数据获取器测试完成")


def test_signal_generator():
    """测试信号生成器。"""
    print("\n=== 测试信号生成器 ===")

    config = {
        "llm_provider": "qwen",
        "deep_think_llm": "qwen3.6-plus",
        "quick_think_llm": "qwen3.6-plus",
        "selected_analysts": ["market"],
        "internal_language": "Chinese",
        "output_language": "Chinese",
    }

    generator = SignalGenerator(
        config=config,
        selected_analysts=["market"],  # 只测试市场分析师
    )

    # 测试预获取数据方法
    status = generator._pre_fetch_data("600400", "2026-05-03", ["market"])
    print(f"预获取状态: {status}")

    print("信号生成器测试完成")


def main():
    """运行所有测试。"""
    print("开始测试智能分析功能...")

    try:
        test_database()
        test_fetcher()
        test_signal_generator()
        print("\n=== 所有测试完成 ===")
    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)