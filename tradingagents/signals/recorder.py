"""信号持久化与加载。"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .types import TradingSignal, SignalRecord


class SignalRecorder:
    """信号记录器，负责信号的持久化与加载。"""

    def __init__(self, storage_dir: str = "signals"):
        """
        初始化信号记录器。

        参数：
            storage_dir: 信号存储目录路径。
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save_signal(self, signal: TradingSignal) -> Path:
        """
        保存信号到JSON文件。

        文件路径结构: storage_dir/YYYY-MM-DD/symbol_signal_id.json

        参数：
            signal: TradingSignal对象。

        返回：
            Path: 保存的文件路径。
        """
        date_dir = self.storage_dir / signal.signal_date
        date_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{signal.symbol}_{signal.signal_id[:8]}.json"
        filepath = date_dir / filename

        record = SignalRecord(signal=signal)
        data = record.to_dict()

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return filepath

    def save_record(self, record: SignalRecord) -> Path:
        """
        保存信号记录（包含执行状态）。

        参数：
            record: SignalRecord对象。

        返回：
            Path: 保存的文件路径。
        """
        signal = record.signal
        date_dir = self.storage_dir / signal.signal_date
        date_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{signal.symbol}_{signal.signal_id[:8]}.json"
        filepath = date_dir / filename

        data = record.to_dict()

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return filepath

    def load_signals(
        self,
        signal_date: str | None = None,
        symbol: str | None = None,
        execution_status: str | None = None,
    ) -> list[SignalRecord]:
        """
        加载信号记录，支持按日期、股票代码、执行状态过滤。

        参数：
            signal_date: 可选，信号日期过滤。
            symbol: 可选，股票代码过滤。
            execution_status: 可选，执行状态过滤。

        返回：
            list[SignalRecord]: 符合条件的信号记录列表。
        """
        records: list[SignalRecord] = []

        # 确定要扫描的目录
        if signal_date:
            dirs_to_scan = [self.storage_dir / signal_date]
        else:
            dirs_to_scan = [d for d in self.storage_dir.iterdir() if d.is_dir()]

        for date_dir in dirs_to_scan:
            if not date_dir.exists():
                continue

            for filepath in date_dir.glob("*.json"):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    record = SignalRecord.from_dict(data)

                    # 应用过滤条件
                    if symbol and record.signal.symbol != symbol:
                        continue
                    if execution_status and record.execution_status != execution_status:
                        continue

                    records.append(record)
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"警告: 无法解析信号文件 {filepath}: {e}")

        # 按日期和创建时间排序
        records.sort(key=lambda r: (r.signal.signal_date, r.signal.created_at))
        return records

    def load_signal_by_id(self, signal_id: str) -> SignalRecord | None:
        """
        根据信号ID加载单个信号记录。

        参数：
            signal_id: 信号UUID。

        返回：
            SignalRecord | None: 找到的信号记录，或None。
        """
        # 扫描所有日期目录
        for date_dir in self.storage_dir.iterdir():
            if not date_dir.is_dir():
                continue

            for filepath in date_dir.glob("*.json"):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("signal_id", "").startswith(signal_id[:8]):
                        return SignalRecord.from_dict(data)
                except (json.JSONDecodeError, KeyError):
                    continue

        return None

    def update_status(
        self,
        signal_id: str,
        status: str,
        execution_price: float | None = None,
        execution_date: str | None = None,
        actual_quantity: int | None = None,
        notes: str = "",
    ) -> bool:
        """
        更新信号的执行状态。

        参数：
            signal_id: 信号UUID。
            status: 新状态 (executed/skipped/expired)。
            execution_price: 执行价格（executed时需要）。
            execution_date: 执行日期（executed时需要）。
            actual_quantity: 实际数量。
            notes: 备注。

        返回：
            bool: 是否成功更新。
        """
        record = self.load_signal_by_id(signal_id)
        if record is None:
            return False

        if status == "executed":
            record.mark_executed(
                price=execution_price or 0.0,
                date=execution_date or datetime.now().strftime("%Y-%m-%d"),
                quantity=actual_quantity,
                notes=notes,
            )
        elif status == "skipped":
            record.mark_skipped(notes)
        elif status == "expired":
            record.mark_expired(notes)
        else:
            record.execution_status = status
            record.notes = notes

        self.save_record(record)
        return True

    def export_to_csv(
        self,
        output_path: Path | str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        """
        导出信号到CSV文件。

        参数：
            output_path: 输出文件路径。
            start_date: 可选，起始日期。
            end_date: 可选，结束日期。

        返回：
            int: 导出的记录数量。
        """
        import csv

        records = self.load_signals()

        # 日期过滤
        if start_date:
            records = [r for r in records if r.signal.signal_date >= start_date]
        if end_date:
            records = [r for r in records if r.signal.signal_date <= end_date]

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "signal_id",
            "symbol",
            "signal_date",
            "action",
            "confidence",
            "suggested_quantity",
            "execution_status",
            "execution_price",
            "execution_date",
            "actual_quantity",
            "rationale",
            "notes",
        ]

        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for record in records:
                row = {
                    "signal_id": record.signal.signal_id,
                    "symbol": record.signal.symbol,
                    "signal_date": record.signal.signal_date,
                    "action": record.signal.action.value,
                    "confidence": record.signal.confidence or "",
                    "suggested_quantity": record.signal.suggested_quantity or "",
                    "execution_status": record.execution_status,
                    "execution_price": record.execution_price or "",
                    "execution_date": record.execution_date or "",
                    "actual_quantity": record.actual_quantity or "",
                    "rationale": record.signal.rationale[:100] + "..." if len(record.signal.rationale) > 100 else record.signal.rationale,
                    "notes": record.notes,
                }
                writer.writerow(row)

        return len(records)

    def get_statistics(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        """
        获取信号统计信息。

        参数：
            start_date: 可选，起始日期。
            end_date: 可选，结束日期。

        返回：
            dict: 统计信息字典。
        """
        records = self.load_signals()

        if start_date:
            records = [r for r in records if r.signal.signal_date >= start_date]
        if end_date:
            records = [r for r in records if r.signal.signal_date <= end_date]

        total = len(records)
        by_action = {}
        by_status = {}
        by_symbol = {}

        for record in records:
            action = record.signal.action.value
            by_action[action] = by_action.get(action, 0) + 1

            status = record.execution_status
            by_status[status] = by_status.get(status, 0) + 1

            symbol = record.signal.symbol
            by_symbol[symbol] = by_symbol.get(symbol, 0) + 1

        return {
            "total_signals": total,
            "by_action": by_action,
            "by_status": by_status,
            "by_symbol": by_symbol,
            "date_range": {
                "start": min(r.signal.signal_date for r in records) if records else None,
                "end": max(r.signal.signal_date for r in records) if records else None,
            },
        }