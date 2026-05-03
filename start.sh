#!/bin/bash
# TradingAgents 启动脚本
# 使用 Python 3.11 环境运行 TradingAgents

# 切换到项目目录
cd "$(dirname "$0")"

# 激活虚拟环境
source ta_env311/bin/activate

# 运行命令
if [ "$1" = "cli" ] || [ -z "$1" ]; then
    # 运行 CLI
    python -m cli.main
elif [ "$1" = "analyze" ]; then
    # 运行分析脚本
    python run_analysis.py
elif [ "$1" = "test" ]; then
    # 运行测试
    python -m unittest discover tests
else
    # 其他命令直接执行
    "$@"
fi