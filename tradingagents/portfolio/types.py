"""组合模块类型定义。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Position:
    """持仓记录。"""

    symbol: str                       # 股票代码
    quantity: int                     # 持仓数量（股）
    entry_date: str                   # 入场日期
    entry_price: float                # 入场价格
    current_price: float = 0.0        # 当前价格
    market_value: float = 0.0         # 市值
    pnl: float = 0.0                  # 盈亏金额
    pnl_pct: float = 0.0              # 盈亏百分比
    notes: str = ""

    def update_price(self, price: float) -> None:
        """更新当前价格并重新计算市值和盈亏。"""
        self.current_price = price
        self.market_value = self.quantity * price
        cost = self.quantity * self.entry_price
        self.pnl = self.market_value - cost
        self.pnl_pct = (self.pnl / cost) if cost > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "market_value": self.market_value,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Position":
        """从字典创建Position。"""
        return cls(
            symbol=data["symbol"],
            quantity=data["quantity"],
            entry_date=data["entry_date"],
            entry_price=data["entry_price"],
            current_price=data.get("current_price", 0.0),
            market_value=data.get("market_value", 0.0),
            pnl=data.get("pnl", 0.0),
            pnl_pct=data.get("pnl_pct", 0.0),
            notes=data.get("notes", ""),
        )


@dataclass
class PortfolioState:
    """组合状态快照。"""

    snapshot_date: str                # 快照日期
    cash: float                       # 现金余额
    positions: list[Position] = field(default_factory=list)
    total_equity: float = 0.0         # 总资产
    realized_pnl: float = 0.0         # 已实现盈亏
    unrealized_pnl: float = 0.0       # 未实现盈亏
    total_pnl: float = 0.0            # 总盈亏
    total_return_pct: float = 0.0     # 总收益率

    def calculate_totals(self) -> None:
        """计算总资产和盈亏。"""
        position_value = sum(p.market_value for p in self.positions)
        self.unrealized_pnl = sum(p.pnl for p in self.positions)
        self.total_equity = self.cash + position_value
        self.total_pnl = self.realized_pnl + self.unrealized_pnl

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "snapshot_date": self.snapshot_date,
            "cash": self.cash,
            "positions": [p.to_dict() for p in self.positions],
            "total_equity": self.total_equity,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_pnl": self.total_pnl,
            "total_return_pct": self.total_return_pct,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PortfolioState":
        """从字典创建PortfolioState。"""
        positions = [Position.from_dict(p) for p in data.get("positions", [])]
        return cls(
            snapshot_date=data["snapshot_date"],
            cash=data["cash"],
            positions=positions,
            total_equity=data.get("total_equity", 0.0),
            realized_pnl=data.get("realized_pnl", 0.0),
            unrealized_pnl=data.get("unrealized_pnl", 0.0),
            total_pnl=data.get("total_pnl", 0.0),
            total_return_pct=data.get("total_return_pct", 0.0),
        )