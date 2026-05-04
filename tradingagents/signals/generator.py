"""交易信号生成器。"""

from datetime import datetime, timedelta
from typing import Any, Optional, List, Dict

from tradingagents.agent_core.types import AgentDecision, DecisionAction
from tradingagents.platform import TradingPlatform
from tradingagents.signals.types import TradingSignal


class SignalGenerator:
    """信号生成器，使用TradingAgents生成交易信号。"""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        signal_storage_dir: str = "signals",
        selected_analysts: Optional[List[str]] = None,
    ):
        """
        初始化信号生成器。

        参数：
            config: 可选，运行配置（LLM provider等）。
            signal_storage_dir: 信号存储目录。
            selected_analysts: 默认启用的分析师列表。
        """
        self.config = config or self._default_config()
        self.default_analysts = selected_analysts or self.config.get("selected_analysts", ["market", "news", "fundamentals"])
        self.storage_dir = signal_storage_dir

        # 初始化平台（但不注册agent，延迟创建）
        self._platform = None

    def _default_config(self) -> Dict[str, Any]:
        """默认配置。"""
        return {
            "llm_provider": "qwen",
            "deep_think_llm": "qwen3.6-plus",
            "quick_think_llm": "qwen3.6-flash",  # 使用更快更经济的模型
            "selected_analysts": ["market", "news", "fundamentals"],
            "internal_language": "Chinese",
            "output_language": "Chinese",
        }

    def _get_platform(
        self,
        selected_analysts: Optional[List[str]] = None,
        callbacks: Optional[List] = None,
    ) -> TradingPlatform:
        """获取或创建平台实例，注册指定分析师的Agent。"""
        analysts = selected_analysts or self.default_analysts

        platform = TradingPlatform(config=self.config)
        platform.register_trading_agents_agent(
            selected_analysts=analysts,
            debug=False,
            callbacks=callbacks,
        )
        return platform

    def generate_for_symbol(
        self,
        symbol: str,
        trade_date: str,
        selected_analysts: Optional[List[str]] = None,
        pre_fetch_data: bool = False,
        callbacks: Optional[List] = None,
    ) -> TradingSignal:
        """
        为单个股票生成交易信号。

        参数：
            symbol: 股票代码。
            trade_date: 交易日期 YYYY-MM-DD。
            selected_analysts: 本次运行的分析师列表（可选）。
            pre_fetch_data: 是否预获取并缓存数据。
            callbacks: LangChain回调处理器列表（可选）。

        返回：
            TradingSignal: 生成的交易信号。
        """
        from tradingagents.agent_core.types import AgentRunRequest

        analysts = selected_analysts or self.default_analysts

        # 如果需要预获取数据，使用CachedDataFetcher
        if pre_fetch_data:
            self._pre_fetch_data(symbol, trade_date, analysts)

        # 获取平台实例（使用指定的分析师和回调）
        platform = self._get_platform(analysts, callbacks=callbacks)

        request = AgentRunRequest(symbol=symbol, trade_date=trade_date)

        try:
            result = platform.run_agent("tradingagents", request)

            if result.decision is None:
                # 无法生成决策，返回HOLD信号
                return TradingSignal.create(
                    symbol=symbol,
                    signal_date=trade_date,
                    action=DecisionAction.HOLD,
                    rationale="Agent未能生成有效决策",
                    metadata={"error": "no_decision"},
                )

            decision = result.decision

            # 提取目标价和止损价（如果有）
            metadata = decision.metadata or {}
            outputs = result.outputs or {}

            signal = TradingSignal.create(
                symbol=symbol,
                signal_date=trade_date,
                action=decision.action,
                rationale=decision.rationale or outputs.get("final_trade_decision_report", ""),
                confidence=decision.confidence,
                suggested_quantity=int(decision.quantity) if decision.quantity else None,
                target_price=metadata.get("target_price"),
                stop_loss=metadata.get("stop_loss"),
                metadata={
                    "raw_signal": outputs.get("raw_signal", ""),
                    "agent_name": decision.agent_name,
                    "holding_period_bars": decision.holding_period_bars,
                    "analysts_used": analysts,
                },
            )

            return signal

        except Exception as e:
            # 发生异常，返回错误信号
            return TradingSignal.create(
                symbol=symbol,
                signal_date=trade_date,
                action=DecisionAction.HOLD,
                rationale=f"生成信号时发生错误: {str(e)}",
                metadata={"error": str(e)},
            )

    def generate_for_watchlist(
        self,
        watchlist: List[str],
        trade_date: str,
        show_progress: bool = True,
        progress_callback: Optional[callable] = None,
    ) -> List[TradingSignal]:
        """
        为关注列表中的所有股票生成信号。

        参数：
            watchlist: 股票代码列表。
            trade_date: 交易日期。
            show_progress: 是否显示进度。
            progress_callback: 进度回调函数，接收 (current, total, symbol, status, signal)。

        返回：
            list[TradingSignal]: 生成的信号列表。
        """
        signals: List[TradingSignal] = []
        total = len(watchlist)

        for idx, symbol in enumerate(watchlist, 1):
            status = "analyzing"

            if progress_callback:
                progress_callback(idx, total, symbol, status, None)

            if show_progress:
                print(f"  [{idx}/{total}] 正在分析 {symbol}...")

            try:
                signal = self.generate_for_symbol(symbol, trade_date)
                signals.append(signal)

                status = "completed"
                if progress_callback:
                    progress_callback(idx, total, symbol, status, signal)

                if show_progress:
                    print(f"  [{idx}/{total}] {symbol} -> {signal.action.value}")
            except Exception as e:
                # 记录错误但继续处理其他股票
                error_signal = TradingSignal.create(
                    symbol=symbol,
                    signal_date=trade_date,
                    action=DecisionAction.HOLD,
                    rationale=f"生成信号失败: {str(e)}",
                    metadata={"error": str(e)},
                )
                signals.append(error_signal)

                status = "error"
                if progress_callback:
                    progress_callback(idx, total, symbol, status, error_signal)

                if show_progress:
                    print(f"  [{idx}/{total}] {symbol} -> ERROR: {str(e)}")

        return signals

    def batch_generate(
        self,
        start_date: str,
        end_date: str,
        watchlist: List[str],
        show_progress: bool = True,
    ) -> Dict[str, List[TradingSignal]]:
        """
        批量生成历史信号（用于回填）。

        参数：
            start_date: 起始日期。
            end_date: 结束日期。
            watchlist: 股票代码列表。
            show_progress: 是否显示进度。

        返回：
            dict: 日期到信号列表的映射。
        """
        from datetime import datetime, timedelta

        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        # 计算交易日数量
        total_days = 0
        current = start
        while current <= end:
            if current.weekday() < 5:
                total_days += 1
            current += timedelta(days=1)

        results: Dict[str, List[TradingSignal]] = {}
        day_idx = 0

        current = start
        while current <= end:
            # 跳过周末
            if current.weekday() < 5:  # 0-4 是周一到周五
                day_idx += 1
                date_str = current.strftime("%Y-%m-%d")

                if show_progress:
                    print(f"\n[{day_idx}/{total_days}] 处理日期: {date_str}")

                signals = self.generate_for_watchlist(watchlist, date_str, show_progress=show_progress)
                results[date_str] = signals

            current += timedelta(days=1)

        return results

    def generate_and_save(
        self,
        watchlist: list[str],
        trade_date: str,
    ) -> list[TradingSignal]:
        """
        生成信号并自动保存到存储目录。

        参数：
            watchlist: 股票代码列表。
            trade_date: 交易日期。

        返回：
            list[TradingSignal]: 生成并保存的信号列表。
        """
        from tradingagents.signals.recorder import SignalRecorder

        signals = self.generate_for_watchlist(watchlist, trade_date)
        recorder = SignalRecorder(self.storage_dir)

        for signal in signals:
            recorder.save_signal(signal)

        return signals

    def _pre_fetch_data(
        self,
        symbol: str,
        trade_date: str,
        analysts: List[str],
    ) -> Dict[str, bool]:
        """
        预获取数据并存入缓存数据库。

        参数：
            symbol: 股票代码。
            trade_date: 交易日期。
            analysts: 要运行的分析师列表。

        返回：
            dict: 各数据源是否有新数据的映射。
        """
        from tradingagents.data_cache import get_fetcher

        fetcher = get_fetcher()
        results = {}

        # 计算日期范围
        end_date = trade_date
        news_start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
        ann_start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d")

        # 根据分析师需要预获取数据
        if "news" in analysts:
            # 获取新闻数据
            news_str, has_new_news = fetcher.fetch_news_with_cache(symbol, news_start, end_date)
            results["news"] = has_new_news

            # 获取公告数据
            ann_str, has_new_ann = fetcher.fetch_announcements_with_cache(symbol, ann_start, end_date)
            results["announcements"] = has_new_ann

        if "social" in analysts:
            # 社交分析师也需要新闻数据
            news_str, has_new = fetcher.fetch_news_with_cache(symbol, news_start, end_date)
            results["social"] = has_new

        if "fundamentals" in analysts:
            # 获取财务数据（使用最近季度）
            quarter_date = fetcher._get_latest_quarter_date(trade_date)
            fin_str, has_new_fin = fetcher.fetch_financials_with_cache(
                symbol, "fundamentals", quarter_date
            )
            results["fundamentals"] = has_new_fin

        return results


def load_watchlist(filepath: str) -> List[str]:
    """
    从CSV文件加载关注列表。

    CSV格式: 第一列为股票代码，可有其他列如名称、行业等。

    参数：
        filepath: CSV文件路径。

    返回：
        list[str]: 股票代码列表。
    """
    import csv
    from pathlib import Path

    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"关注列表文件不存在: {filepath}")

    symbols: List[str] = []

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)  # 跳过标题行

        for row in reader:
            if row and row[0]:
                symbols.append(row[0].strip())

    return symbols