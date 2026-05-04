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
python3 run_analysis.py
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
python3 -m unittest discover tests
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
python3 -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.environ.get('QWEN_API_KEY'))"
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

---

## 量化交易扩展功能

### 信号生成器 (Phase 1)

TradingAgents 可以作为投资信号生成器，为你的关注列表生成每日交易信号。

#### 生成每日信号

```bash
# 激活环境
source ta_env311/bin/activate

# 为关注列表生成当日信号（快速模式，默认）
python3 scripts/generate_signals.py --watchlist watchlist.csv

# 指定日期生成
python3 scripts/generate_signals.py --watchlist watchlist.csv --date 2024-05-10

# 深度分析模式（更多辩论轮数）
python3 scripts/generate_signals.py --watchlist watchlist.csv --depth 3

# 自定义分析师组合
python3 scripts/generate_signals.py --watchlist watchlist.csv --analysts market,news

# 批量回填历史信号
python3 scripts/generate_signals.py --backfill --start 2024-01-01 --end 2024-05-01 --watchlist watchlist.csv
```

#### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--watchlist` | 关注列表CSV文件 | `watchlist.csv` |
| `--date` | 交易日期 | 当天 |
| `--depth` | 研究深度: 1=快速, 3=中等, 5=深度 | `1` |
| `--analysts` | 分析师列表(逗号分隔): market, news, fundamentals, social | `market,news,fundamentals` |
| `--provider` | LLM提供商 | `qwen` |
| `--model` | LLM模型 | `qwen3.6-plus` |

**研究深度对比：**

| 深度 | 辩论轮数 | 风险讨论轮数 | 适用场景 |
|------|---------|-------------|---------|
| 1 (快速) | 1轮 | 1轮 | 每日快速扫描，大量股票 |
| 3 (中等) | 3轮 | 3轮 | 常规分析，平衡速度与深度 |
| 5 (深度) | 5轮 | 5轮 | 重点股票深度研究 |

**时间预估 (10个股票)：**

| 深度 | 分析师数 | 预计时间 |
|------|---------|---------|
| 1 | 1 (仅market) | 3-5分钟 |
| 1 | 3 | 5-8分钟 |
| 3 | 3 | 10-15分钟 |
| 5 | 3 | 15-25分钟 |

#### Web Dashboard

启动 Web 界面查看和管理信号：

```bash
# 启动 Web Dashboard
python3 scripts/start_web.py

# 或指定端口
python3 scripts/start_web.py --port 8080
```

打开浏览器访问 `http://localhost:5000`，可以：
- 查看信号统计和组合状态
- 浏览信号列表，标记执行状态
- 手动管理组合（买入/卖出）
- 查看权益曲线

#### 信号存储结构

信号保存在 `signals/` 目录下：
```
signals/
├── 2024-05-10/
│   ├── 600519_abc12345.json
│   ├── 000858_def67890.json
│   └── ...
├── 2024-05-11/
│   └── ...
```

每个信号文件包含：
- 股票代码、日期、动作 (BUY/SELL/HOLD)
- 决策理由、置信度
- 建议数量、目标价、止损价
- 执行状态、执行价格

#### 关注列表格式

`watchlist.csv` 文件格式：
```csv
symbol,name,sector
600519,贵州茅台,白酒
000858,五粮液,白酒
601318,中国平安,保险
```

### 组合回测系统 (Phase 2)

支持组合级回测，包含交易成本和风险指标计算。

#### A股交易成本模型

```python
from tradingagents.backtesting import TransactionCostCalculator, TransactionCostConfig

# 默认A股成本配置
config = TransactionCostConfig(
    commission_rate=0.0003,    # 佣金 0.03% (标准)，量化优待可用0.0001
    commission_min=5.0,        # 最低5元
    stamp_duty_rate=0.0005,    # 印花税 0.05% (仅卖出)
    transfer_fee_rate=0.0001,  # 过户费 0.01% (沪市，范围0.0001~0.0002)
)

calc = TransactionCostCalculator(config)

# 计算买入成本（假设沪市股票600519）
buy_costs = calc.calculate_buy_costs(price=1680.0, quantity=100, sh_market=True)
print(f"买入成本: {buy_costs['total_cost']:.2f}元")

# 计算卖出成本
sell_costs = calc.calculate_sell_costs(price=1750.0, quantity=100, sh_market=True)
print(f"卖出成本: {sell_costs['total_cost']:.2f}元")
```

**A股交易成本说明：**
| 项目 | 买入 | 卖出 | 备注 |
|------|------|------|------|
| 佣金 | 0.03% | 0.03% | 最低5元，量化优待0.01% |
| 印花税 | 无 | 0.05% | 仅卖出方收取 |
| 过户费 | 0.01% | 0.01% | 仅沪市股票（6开头） |
```

#### 绩效指标计算

```python
from tradingagents.backtesting import PerformanceMetricsCalculator

# 计算夏普比率
sharpe = PerformanceMetricsCalculator.sharpe_ratio(daily_returns, risk_free_rate=0.02)

# 计算最大回撤
max_dd, start_idx, end_idx = PerformanceMetricsCalculator.max_drawdown(equity_curve)

# 计算年化收益
annual_ret = PerformanceMetricsCalculator.annualized_return(total_return=15.0, num_days=60)

# 计算所有指标
metrics = PerformanceMetricsCalculator.calculate_all(
    equity_curve=[100000, 102000, 105000, 103000, 108000],
    trades=[{"return_pct": 2.5}, {"return_pct": -1.0}, {"return_pct": 5.0}],
    initial_capital=100000,
)
```

#### 组合级回测

```python
from tradingagents.backtesting import PortfolioBacktestEngine, PortfolioBacktestReport
from tradingagents.agent_core.types import AgentDecision, DecisionAction

# 创建组合回测引擎
engine = PortfolioBacktestEngine(
    initial_capital=100000,       # 初始资金10万
    max_position_pct=0.2,         # 单只最大20%仓位
    max_positions=5,              # 最多持有5只
)

# 准备决策数据（从信号加载）
decisions = [
    AgentDecision(
        agent_name="tradingagents",
        symbol="600519",
        trade_date="2024-05-10",
        action=DecisionAction.BUY,
        quantity=100,
        holding_period_bars=5,
    ),
    # ... 更多决策
]

# 准备日线数据（从AkShare获取）
from tradingagents.dataflows.a_share import get_stock_data
daily_data_map = {
    "600519": get_stock_data("600519", "2024-01-01", "2024-06-01"),
    # ... 更多股票
}

# 执行回测
report = engine.backtest_decisions(decisions, daily_data_map)

# 查看结果
print(f"总收益: {report.total_return:.2f}%")
print(f"年化收益: {report.annualized_return:.2f}%")
print(f"夏普比率: {report.sharpe_ratio:.2f}")
print(f"最大回撤: {report.max_drawdown:.2f}%")
print(f"胜率: {report.win_rate:.1f}%")
print(f"总交易成本: {report.total_costs:.2f}元")
```

### 手动组合追踪

使用 `ManualPortfolioTracker` 记录和管理你的实际持仓：

```python
from tradingagents.portfolio import ManualPortfolioTracker

# 创建追踪器（初始资金10万）
tracker = ManualPortfolioTracker(initial_capital=100000)

# 买入
tracker.buy(symbol="600519", quantity=100, price=1680.0, date="2024-05-10")

# 卖出
pnl = tracker.sell(symbol="600519", quantity=100, price=1750.0, date="2024-05-20")
print(f"已实现盈亏: {pnl:.2f}元")

# 更新价格
tracker.update_prices({"600519": 1700.0})

# 获取当前状态
state = tracker.get_state("2024-05-15")
print(f"总资产: {state.total_equity:.2f}元")
print(f"收益率: {state.total_return_pct:.2f}%")

# 保存快照
tracker.save_snapshot("2024-05-15")

# 查看权益曲线
curve = tracker.get_equity_curve()
```

### 完整工作流程示例

```python
# 1. 生成信号
from tradingagents.signals import SignalGenerator, SignalRecorder

generator = SignalGenerator()
signals = generator.generate_and_save(["600519", "000858"], "2024-05-10")

# 2. 查看信号
recorder = SignalRecorder()
pending_signals = recorder.load_signals(execution_status="pending")

# 3. 执行交易（通过Web界面或手动）
tracker = ManualPortfolioTracker(initial_capital=100000)
for record in pending_signals:
    if record.signal.action.value == "BUY":
        tracker.buy(record.signal.symbol, 100, current_price, "2024-05-11")
        recorder.update_status(record.signal.signal_id, "executed", current_price, "2024-05-11")

# 4. 回测验证策略
engine = PortfolioBacktestEngine(initial_capital=100000)
# 加载历史信号作为决策...
report = engine.backtest_decisions(decisions, daily_data_map)

# 5. 评估绩效
print(f"策略夏普比率: {report.sharpe_ratio:.2f}")
print(f"策略最大回撤: {report.max_drawdown:.2f}%")
```

### 使用Web界面回测

启动Web Dashboard后，访问回测页面：

```bash
python3 scripts/start_web.py
# 打开 http://localhost:5000/backtest
```

在Web界面可以：
- 设置回测参数（日期范围、资金、仓位限制）
- 查看回测报告（收益、风险指标、交易明细）
- 查看历史回测报告列表
- 对比不同参数的回测结果

### 使用命令行回测

```bash
# 使用已生成的信号执行回测
python3 scripts/run_backtest.py --start 2024-04-01 --end 2024-05-10

# 自定义参数
python3 scripts/run_backtest.py \
    --start 2024-04-01 \
    --end 2024-05-10 \
    --capital 500000 \
    --max-position-pct 0.1 \
    --max-positions 3 \
    --commission-rate 0.0003 \
    --stamp-duty-rate 0.0005 \
    --output backtest_results/my_report.json
```

**回测前置条件：**
必须先生成历史信号：
```bash
python3 scripts/generate_signals.py --backfill --start 2024-04-01 --end 2024-05-01 --watchlist watchlist.csv
```