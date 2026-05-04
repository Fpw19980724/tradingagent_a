"""信号模块类型定义。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from tradingagents.agent_core.types import DecisionAction


@dataclass(frozen=True)
class TradingSignal:
    """交易信号，包含完整的决策上下文。"""

    signal_id: str                    # UUID唯一标识
    symbol: str                       # 股票代码
    signal_date: str                  # 信号日期 YYYY-MM-DD
    action: DecisionAction            # BUY/SELL/HOLD
    rationale: str                    # 决策理由
    confidence: float | None = None   # 置信度 (0-1)
    suggested_quantity: int | None = None  # 建议仓位（股数）
    target_price: float | None = None       # 目标价
    stop_loss: float | None = None          # 止损价
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def create(
        cls,
        symbol: str,
        signal_date: str,
        action: DecisionAction,
        rationale: str,
        confidence: float | None = None,
        suggested_quantity: int | None = None,
        target_price: float | None = None,
        stop_loss: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "TradingSignal":
        """创建新信号，自动生成UUID和时间戳。"""
        return cls(
            signal_id=str(uuid4()),
            symbol=symbol,
            signal_date=signal_date,
            action=action,
            rationale=rationale,
            confidence=confidence,
            suggested_quantity=suggested_quantity,
            target_price=target_price,
            stop_loss=stop_loss,
            metadata=metadata or {},
        )


@dataclass
class SignalRecord:
    """持久化的信号记录，包含执行状态。"""

    signal: TradingSignal
    execution_status: str = "pending"  # pending/executed/skipped/expired
    execution_price: float | None = None
    execution_date: str | None = None
    actual_quantity: int | None = None
    notes: str = ""

    def mark_executed(
        self,
        price: float,
        date: str,
        quantity: int | None = None,
        notes: str = "",
    ) -> None:
        """标记信号已执行。"""
        self.execution_status = "executed"
        self.execution_price = price
        self.execution_date = date
        self.actual_quantity = quantity or self.signal.suggested_quantity
        self.notes = notes

    def mark_skipped(self, reason: str = "") -> None:
        """标记信号已跳过。"""
        self.execution_status = "skipped"
        self.notes = reason

    def mark_expired(self, reason: str = "") -> None:
        """标记信号已过期。"""
        self.execution_status = "expired"
        self.notes = reason

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式用于JSON序列化。"""
        return {
            "signal_id": self.signal.signal_id,
            "symbol": self.signal.symbol,
            "signal_date": self.signal.signal_date,
            "action": self.signal.action.value,
            "rationale": self.signal.rationale,
            "confidence": self.signal.confidence,
            "suggested_quantity": self.signal.suggested_quantity,
            "target_price": self.signal.target_price,
            "stop_loss": self.signal.stop_loss,
            "metadata": self.signal.metadata,
            "created_at": self.signal.created_at,
            "execution_status": self.execution_status,
            "execution_price": self.execution_price,
            "execution_date": self.execution_date,
            "actual_quantity": self.actual_quantity,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalRecord":
        """从字典创建SignalRecord。"""
        signal = TradingSignal(
            signal_id=data["signal_id"],
            symbol=data["symbol"],
            signal_date=data["signal_date"],
            action=DecisionAction(data["action"]),
            rationale=data["rationale"],
            confidence=data.get("confidence"),
            suggested_quantity=data.get("suggested_quantity"),
            target_price=data.get("target_price"),
            stop_loss=data.get("stop_loss"),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", ""),
        )
        return cls(
            signal=signal,
            execution_status=data.get("execution_status", "pending"),
            execution_price=data.get("execution_price"),
            execution_date=data.get("execution_date"),
            actual_quantity=data.get("actual_quantity"),
            notes=data.get("notes", ""),
        )