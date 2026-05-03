# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TradingAgents-A股版 is a multi-agent LLM trading research framework focused on Chinese A-share market analysis. It orchestrates multiple AI agents (Analysts, Researchers, Trader, Risk Management, Portfolio Manager) through LangGraph to produce trading decisions.

## Common Commands

```bash
# Install the package
pip install -e .

# Run CLI (interactive analysis)
tradingagents
# or
python -m cli.main

# Run tests
python -m unittest discover tests

# Run a single test file
python -m unittest tests.test_a_share_dataflows

# Quick test script (dataflows validation)
python test.py

# Run main.py (platform example)
python main.py
```

## Environment Setup

Copy `.env.example` to `.env` and configure at least one LLM provider API key:
- `OPENAI_API_KEY`
- `AZURE_API_KEY` (with `backend_url` for Azure endpoint)
- `GOOGLE_API_KEY`
- `ANTHROPIC_API_KEY`
- `XAI_API_KEY`
- `OPENROUTER_API_KEY`
- `QWEN_API_KEY`

## Architecture

### Multi-Agent Workflow (LangGraph)

The trading decision pipeline flows through 5 teams:

1. **Analyst Team** (`tradingagents/agents/analysts/`) - Four optional analysts:
   - Market Analyst: technical indicators, price data
   - Social/Sentiment Analyst: social media sentiment
   - News Analyst: company news, market news, announcements
   - Fundamentals Analyst: financial statements, company profile

2. **Research Team** (`tradingagents/agents/researchers/`) - Fixed:
   - Bull Researcher vs Bear Researcher debate
   - Research Manager synthesizes debate into investment plan

3. **Trading Team** (`tradingagents/agents/trader/`) - Fixed:
   - Trader creates execution plan from research output

4. **Risk Management** (`tradingagents/agents/risk_mgmt/`) - Fixed:
   - Aggressive, Conservative, Neutral analysts debate risks
   - Judge evaluates risk perspectives

5. **Portfolio Management** (`tradingagents/agents/managers/`) - Fixed:
   - Portfolio Manager makes final decision
   - Report Finalizer formats output

### Core Modules

- `tradingagents/graph/` - LangGraph orchestration:
  - `trading_graph.py`: main graph class `TradingAgentsGraph`
  - `setup.py`: graph construction and node wiring
  - `propagation.py`: state initialization and execution args
  - `conditional_logic.py`: debate round limits, transition conditions

- `tradingagents/llm_clients/` - Multi-provider LLM abstraction:
  - `factory.py`: `create_llm_client(provider, model, ...)` - entry point
  - `azure_client.py`: Azure OpenAI with content filter retry logic
  - `openai_client.py`: OpenAI, Ollama, OpenRouter, xAI, Qwen
  - `anthropic_client.py`, `google_client.py`: respective providers

- `tradingagents/dataflows/` - A-share data tools (AkShare):
  - `a_share.py`: all data functions - `get_stock_data`, `get_indicators`, `get_fundamentals`, `get_news`, etc.
  - `interface.py`: abstract interface for potential other data sources
  - `config.py`: runtime configuration injection

- `tradingagents/platform.py` - `TradingPlatform` class:
  - Unified entry point combining data tools, agents, and backtesting
  - `register_trading_agents_agent()` to use built-in implementation
  - `run_agent()` and `backtest_agent()` for execution

### CLI (`cli/`)

Interactive terminal interface using Typer + Rich:
- `main.py`: entry point, `run_analysis()` orchestrates full workflow
- User selects: ticker symbol, analysis date, analysts, research depth, LLM provider/model
- Real-time progress display with agent status, messages, and report sections

## Key Patterns

### Creating LLM Clients

```python
from tradingagents.llm_clients import create_llm_client

client = create_llm_client(
    provider="openai",  # or "azure", "anthropic", "google", etc.
    model="gpt-4o",
    base_url=None,  # required for Azure
    reasoning_effort="high",  # OpenAI/Azure specific
)
llm = client.get_llm()  # returns LangChain-compatible LLM object
```

### Running Analysis Programmatically

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"
config["deep_think_llm"] = "gpt-4o"
config["quick_think_llm"] = "gpt-4o-mini"

graph = TradingAgentsGraph(
    selected_analysts=["market", "news", "fundamentals"],
    config=config,
    debug=True,
)
final_state, decision = graph.propagate("600519", "2024-05-10")
```

### Using TradingPlatform

```python
from tradingagents.platform import TradingPlatform
from tradingagents.agent_core.types import AgentRunRequest

platform = TradingPlatform(config=config)
platform.register_trading_agents_agent(debug=True)

result = platform.run_agent(
    "tradingagents",
    AgentRunRequest(symbol="600519", trade_date="2024-05-10"),
)
print(result.decision.action.value)
```

## Configuration (`tradingagents/default_config.py`)

Key config keys:
- `llm_provider`: "openai", "azure", "anthropic", "google", etc.
- `deep_think_llm` / `quick_think_llm`: model names for different agent roles
- `selected_analysts`: list of enabled analysts (e.g., `["market", "news"]`)
- `max_debate_rounds`: research debate rounds (affects depth)
- `max_risk_discuss_rounds`: risk debate rounds
- `internal_language`: language for agent reasoning ("English" or "Chinese")
- `output_language` / `final_output_language`: report output language
- `data_vendors`: data source config (default: AkShare for all categories)

## Testing Notes

Tests use `unittest` with `unittest.mock.patch` to mock AkShare API calls. Test files follow pattern `test_<module>.py` in `tests/` directory.

When writing tests for dataflows, mock the specific `ak.*` function being called (e.g., `ak.stock_zh_a_hist` for `get_stock_data`).