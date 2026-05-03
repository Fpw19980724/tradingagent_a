#!/usr/bin/env python
"""非交互式运行 TradingAgents 分析"""

import os

# 设置环境变量以解决 IPv6 连接超时和 mini_racer 崩溃问题
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("HTTP_PROXY", "")
os.environ.setdefault("HTTPS_PROXY", "")
os.environ.setdefault("ALL_PROXY", "")
os.environ.setdefault("LANGCHAIN_OPENAI_TCP_KEEPALIVE", "0")

from dotenv import load_dotenv
load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# 配置
config = DEFAULT_CONFIG.copy()
config['llm_provider'] = 'qwen'
config['deep_think_llm'] = 'qwen3.6-plus'
config['quick_think_llm'] = 'qwen3.6-plus'
config['backend_url'] = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
config['selected_analysts'] = ['market', 'news', 'fundamentals']
config['max_debate_rounds'] = 1
config['max_risk_discuss_rounds'] = 1

# 选择股票和日期
ticker = '600519'  # 贵州茅台
trade_date = '2024-05-10'

print(f'分析标的: {ticker}')
print(f'分析日期: {trade_date}')
print(f'启用分析师: {config["selected_analysts"]}')
print()

# 创建图
print('初始化 TradingAgentsGraph...')
graph = TradingAgentsGraph(
    selected_analysts=config['selected_analysts'],
    config=config,
    debug=True,
)

# 执行分析
print('开始执行分析...')
final_state, decision = graph.propagate(ticker, trade_date)

print()
print('=' * 60)
print('分析完成！')
print('=' * 60)
print()
print('最终决策:')
print(decision)
print()
print('完整状态已保存到 eval_results/ 目录')