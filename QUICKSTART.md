# TradingAgents 使用指南

## 环境要求

- Python 3.11（推荐）
- macOS / Linux

> 注意：Python 3.14 存在 IPv6 连接和 mini_racer 兼容性问题，请使用 Python 3.11。

## 安装

### 1. 创建虚拟环境

```bash
/usr/local/bin/python3.11 -m venv ta_env311
source ta_env311/bin/activate
```

### 2. 安装依赖

```bash
pip install -e .
```

## 配置

### 1. 复制环境变量模板

```bash
cp .env.example .env
```

### 2. 编辑 `.env` 文件，填入你的 API 密钥

```bash
# 必填：选择一个 LLM 提供方的 API 密钥
QWEN_API_KEY=你的密钥
# 或
OPENAI_API_KEY=你的密钥
# 或
ANTHROPIC_API_KEY=你的密钥
```

## 使用方法

### 方法 1：CLI 交互式界面

```bash
source ta_env311/bin/activate
tradingagents
```

或：

```bash
./start.sh cli
```

### 方法 2：分析脚本

编辑 `run_analysis.py` 中的参数后运行：

```bash
source ta_env311/bin/activate
python run_analysis.py
```

或：

```bash
./start.sh analyze
```

### 方法 3：Python API

```python
import tradingagents  # 自动加载环境配置

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# 配置
config = DEFAULT_CONFIG.copy()
config['llm_provider'] = 'qwen'
config['deep_think_llm'] = 'qwen3.6-plus'
config['quick_think_llm'] = 'qwen3.6-plus'
config['selected_analysts'] = ['market', 'news', 'fundamentals']

# 运行分析
graph = TradingAgentsGraph(
    selected_analysts=config['selected_analysts'],
    config=config,
    debug=True,
)
final_state, decision = graph.propagate('600519', '2024-05-10')
print(decision)
```

### 方法 4：TradingPlatform API

```python
import tradingagents
from tradingagents.platform import TradingPlatform
from tradingagents.agent_core.types import AgentRunRequest

platform = TradingPlatform()
platform.register_trading_agents_agent(debug=True)

result = platform.run_agent(
    "tradingagents",
    AgentRunRequest(symbol="600519", trade_date="2024-05-10"),
)
print(result.decision.action.value)
```

## 支持的 LLM 提供方

| 提供方 | 环境变量 | 模型示例 |
|--------|----------|----------|
| Qwen (阿里云) | `QWEN_API_KEY` | `qwen3.6-plus` |
| OpenAI | `OPENAI_API_KEY` | `gpt-4o` |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` |
| Google | `GOOGLE_API_KEY` | `gemini-2.5-pro` |
| xAI | `XAI_API_KEY` | `grok-4` |
| OpenRouter | `OPENROUTER_API_KEY` | 兼容多模型 |

## 运行测试

```bash
source ta_env311/bin/activate
python -m unittest discover tests
```

或：

```bash
./start.sh test
```

## 数据来源

Analyst Team 通过 AkShare API 获取 A 股市场数据：

- **Market Analyst**: 股票行情、技术指标（东方财富）
- **News Analyst**: 公司新闻、市场快讯、公告（东方财富、巨潮资讯）
- **Fundamentals Analyst**: 财务报表、公司概况（东方财富、同花顺）
- **Social Analyst**: 个股新闻舆情（东方财富）

## 常见问题

### Q: 报错 `mini_racer` crash

确保使用 Python 3.11 并安装正确版本：
```bash
pip install mini-racer==0.12.4
```

### Q: 报错 SSL 连接超时

项目已内置 IPv4 强制连接修复。如仍有问题，检查网络代理设置。

### Q: 报错 API Key 未设置

确保 `.env` 文件存在并包含有效的 API 密钥：
```bash
source ta_env311/bin/activate
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.environ.get('QWEN_API_KEY'))"
```

## 目录结构

```
tradingagents/
├── agents/          # 各类 Agent 实现
├── graph/           # LangGraph 工作流编排
├── dataflows/       # A 股数据工具
├── llm_clients/     # 多提供方 LLM 客户端
├── platform.py      # 统一入口平台
└── default_config.py # 默认配置

cli/                 # 交互式 CLI
tests/               # 单元测试
run_analysis.py      # 非交互式分析脚本
start.sh             # 启动脚本
.env                 # 环境变量配置
```

## 更多信息

- 详细架构说明：见 `CLAUDE.md`
- 原项目文档：见 `README.md`