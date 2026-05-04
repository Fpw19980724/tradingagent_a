from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class DecisionAction(str, Enum):
    """标准化的交易动作枚举。"""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class AgentDecision:
    """定义 Agent 输出给回测层的标准化决策。"""

    agent_name: str
    symbol: str
    trade_date: str
    action: DecisionAction
    rationale: str = ""
    confidence: Optional[float] = None
    quantity: float = 1.0
    decision_time: Optional[str] = None
    holding_period_bars: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRunRequest:
    """描述一次 Agent 独立运行请求。"""

    symbol: str
    trade_date: str
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRunResult:
    """描述一次 Agent 运行结果。"""

    agent_name: str
    decision: Optional[AgentDecision]
    outputs: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentExecutionContext:
    """描述 Agent 运行时可访问的共享能力。"""

    config: Dict[str, Any]
    data_tools: Any
    market_tools: Any
