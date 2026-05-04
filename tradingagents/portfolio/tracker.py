"""手动组合追踪管理。"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .types import Position, PortfolioState


class ManualPortfolioTracker:
    """手动组合追踪器，用于记录和管理持仓状态。"""

    def __init__(
        self,
        initial_capital: float = 100000.0,
        storage_dir: str = "portfolio",
    ):
        """
        初始化组合追踪器。

        参数：
            initial_capital: 初始资金。
            storage_dir: 存储目录路径。
        """
        self.initial_capital = initial_capital
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.cash = initial_capital
        self.positions: dict[str, Position] = {}
        self.history: list[PortfolioState] = []
        self.realized_pnl: float = 0.0

        # 尝试加载历史数据
        self.load_from_history()

    def buy(
        self,
        symbol: str,
        quantity: int,
        price: float,
        date: str,
        notes: str = "",
    ) -> Position:
        """
        买入操作，添加新持仓。

        参数：
            symbol: 股票代码。
            quantity: 买入数量（股）。
            price: 买入价格。
            date: 交易日期。
            notes: 备注。

        返回：
            Position: 创建的持仓对象。

        异常：
            ValueError: 如果现金不足。
        """
        cost = quantity * price

        if cost > self.cash:
            raise ValueError(f"现金不足: 需要 {cost:.2f}, 可用 {self.cash:.2f}")

        self.cash -= cost

        # 如果已有持仓，更新数量和均价
        if symbol in self.positions:
            existing = self.positions[symbol]
            total_quantity = existing.quantity + quantity
            total_cost = existing.quantity * existing.entry_price + cost
            avg_price = total_cost / total_quantity

            existing.quantity = total_quantity
            existing.entry_price = avg_price
            existing.notes = notes
            existing.update_price(price)
        else:
            position = Position(
                symbol=symbol,
                quantity=quantity,
                entry_date=date,
                entry_price=price,
                current_price=price,
                notes=notes,
            )
            position.market_value = quantity * price
            self.positions[symbol] = position

        return self.positions[symbol]

    def sell(
        self,
        symbol: str,
        quantity: int | None = None,
        price: float = 0.0,
        date: str = "",
        notes: str = "",
    ) -> float:
        """
        卖出操作，关闭或减少持仓。

        参数：
            symbol: 股票代码。
            quantity: 卖出数量，None表示全部卖出。
            price: 卖出价格。
            date: 交易日期。
            notes: 备注。

        返回：
            float: 已实现盈亏金额。

        异常：
            ValueError: 如果持仓不存在或数量不足。
        """
        if symbol not in self.positions:
            raise ValueError(f"无持仓: {symbol}")

        position = self.positions[symbol]

        if quantity is None:
            quantity = position.quantity

        if quantity > position.quantity:
            raise ValueError(f"卖出数量超过持仓: 需要 {quantity}, 持有 {position.quantity}")

        revenue = quantity * price
        cost = quantity * position.entry_price
        pnl = revenue - cost

        self.cash += revenue
        self.realized_pnl += pnl

        if quantity == position.quantity:
            # 全部卖出，删除持仓
            del self.positions[symbol]
        else:
            # 部分卖出，更新持仓
            position.quantity -= quantity
            position.update_price(price)

        return pnl

    def update_prices(self, prices: dict[str, float]) -> None:
        """
        更新所有持仓的当前价格。

        参数：
            prices: 股票代码到价格的映射。
        """
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol].update_price(price)

    def get_state(self, snapshot_date: str) -> PortfolioState:
        """
        获取当前组合状态快照。

        参数：
            snapshot_date: 快照日期。

        返回：
            PortfolioState: 组合状态。
        """
        positions_list = list(self.positions.values())
        state = PortfolioState(
            snapshot_date=snapshot_date,
            cash=self.cash,
            positions=positions_list,
            realized_pnl=self.realized_pnl,
        )
        state.calculate_totals()
        state.total_return_pct = (state.total_equity - self.initial_capital) / self.initial_capital * 100
        return state

    def save_snapshot(self, snapshot_date: str | None = None) -> Path:
        """
        保存组合状态快照到文件。

        参数：
            snapshot_date: 可选，快照日期，默认使用当前日期。

        返回：
            Path: 保存的文件路径。
        """
        if snapshot_date is None:
            snapshot_date = datetime.now().strftime("%Y-%m-%d")

        state = self.get_state(snapshot_date)
        self.history.append(state)

        filename = f"{snapshot_date}.json"
        filepath = self.storage_dir / "snapshots" / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)

        data = state.to_dict()

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return filepath

    def load_from_history(self) -> bool:
        """
        从历史快照加载组合状态。

        返回：
            bool: 是否成功加载。
        """
        snapshots_dir = self.storage_dir / "snapshots"
        if not snapshots_dir.exists():
            return False

        # 获取最新的快照
        snapshot_files = sorted(snapshots_dir.glob("*.json"), reverse=True)
        if not snapshot_files:
            return False

        try:
            with open(snapshot_files[0], "r", encoding="utf-8") as f:
                data = json.load(f)

            state = PortfolioState.from_dict(data)

            self.cash = state.cash
            self.realized_pnl = state.realized_pnl
            self.positions = {p.symbol: p for p in state.positions}

            return True
        except (json.JSONDecodeError, KeyError) as e:
            print(f"警告: 无法加载组合快照: {e}")
            return False

    def get_equity_curve(self) -> list[dict[str, Any]]:
        """
        从历史快照生成权益曲线。

        返回：
            list: 权益曲线数据点列表。
        """
        snapshots_dir = self.storage_dir / "snapshots"
        if not snapshots_dir.exists():
            return []

        curve = []
        snapshot_files = sorted(snapshots_dir.glob("*.json"))

        for filepath in snapshot_files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                curve.append({
                    "date": data["snapshot_date"],
                    "equity": data["total_equity"],
                    "cash": data["cash"],
                    "positions_value": data["total_equity"] - data["cash"],
                    "pnl": data["total_pnl"],
                    "return_pct": data["total_return_pct"],
                })
            except (json.JSONDecodeError, KeyError):
                continue

        return curve

    def get_positions_summary(self) -> dict[str, Any]:
        """
        获取当前持仓摘要。

        返回：
            dict: 持仓摘要信息。
        """
        positions_list = list(self.positions.values())
        total_market_value = sum(p.market_value for p in positions_list)
        total_pnl = sum(p.pnl for p in positions_list)

        return {
            "cash": self.cash,
            "positions_count": len(positions_list),
            "positions_value": total_market_value,
            "total_equity": self.cash + total_market_value,
            "unrealized_pnl": total_pnl,
            "realized_pnl": self.realized_pnl,
            "total_pnl": total_pnl + self.realized_pnl,
            "initial_capital": self.initial_capital,
            "return_pct": (self.cash + total_market_value - self.initial_capital) / self.initial_capital * 100,
            "positions": [p.to_dict() for p in positions_list],
        }

    def reset(self) -> None:
        """
        重置组合状态到初始状态。
        """
        self.cash = self.initial_capital
        self.positions.clear()
        self.realized_pnl = 0.0
        self.history.clear()