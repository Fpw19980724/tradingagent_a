"""Web Dashboard - Flask应用。"""

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue, Empty

import pandas as pd
from flask import Flask, jsonify, render_template, request, Response

from tradingagents.signals import SignalRecorder, SignalGenerator, load_watchlist
from tradingagents.portfolio import ManualPortfolioTracker
from tradingagents.backtesting import PortfolioBacktestEngine, TransactionCostConfig
from tradingagents.agent_core.types import AgentDecision, DecisionAction
from tradingagents.dataflows.a_share import get_stock_data

app = Flask(__name__)

# 全局实例（懒加载）
_recorder: SignalRecorder | None = None
_tracker: ManualPortfolioTracker | None = None


def get_recorder() -> SignalRecorder:
    """获取SignalRecorder实例。"""
    global _recorder
    if _recorder is None:
        _recorder = SignalRecorder()
    return _recorder


def get_tracker() -> ManualPortfolioTracker:
    """获取ManualPortfolioTracker实例。"""
    global _tracker
    if _tracker is None:
        _tracker = ManualPortfolioTracker()
    return _tracker


def save_report_to_disk(final_state: dict, ticker: str, save_path: Path) -> Path:
    """
    将完整分析报告按目录结构保存到磁盘（与CLI一致）。

    参数：
        final_state: 工作流执行完成后的最终状态。
        ticker: 股票代码。
        save_path: 保存目录路径。

    返回：
        Path: 完整报告文件路径。
    """
    save_path.mkdir(parents=True, exist_ok=True)
    sections = []

    # 1. 分析师团队报告
    analysts_dir = save_path / "1_analysts"
    analyst_parts = []
    if final_state.get("final_market_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "market_report.md").write_text(final_state["final_market_report"], encoding="utf-8")
        analyst_parts.append(("Market Analyst", final_state["final_market_report"]))
    if final_state.get("final_sentiment_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "sentiment_report.md").write_text(final_state["final_sentiment_report"], encoding="utf-8")
        analyst_parts.append(("Social Analyst", final_state["final_sentiment_report"]))
    if final_state.get("final_news_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "news_report.md").write_text(final_state["final_news_report"], encoding="utf-8")
        analyst_parts.append(("News Analyst", final_state["final_news_report"]))
    if final_state.get("final_fundamentals_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "fundamentals_report.md").write_text(final_state["final_fundamentals_report"], encoding="utf-8")
        analyst_parts.append(("Fundamentals Analyst", final_state["final_fundamentals_report"]))
    if analyst_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
        sections.append(f"## I. Analyst Team Reports\n\n{content}")

    # 2. 研究团队决策
    if final_state.get("final_investment_plan_report"):
        research_dir = save_path / "2_research"
        research_dir.mkdir(exist_ok=True)
        (research_dir / "investment_plan.md").write_text(final_state["final_investment_plan_report"], encoding="utf-8")
        sections.append(f"## II. Research Team Decision\n\n{final_state['final_investment_plan_report']}")

    # 3. 交易团队计划
    if final_state.get("final_trader_investment_plan_report"):
        trading_dir = save_path / "3_trading"
        trading_dir.mkdir(exist_ok=True)
        (trading_dir / "trader_investment_plan_report.md").write_text(final_state["final_trader_investment_plan_report"], encoding="utf-8")
        sections.append(f"## III. Trading Team Plan\n\n{final_state['final_trader_investment_plan_report']}")

    # 4. 组合管理决策
    if final_state.get("final_trade_decision_report"):
        portfolio_dir = save_path / "4_portfolio"
        portfolio_dir.mkdir(exist_ok=True)
        (portfolio_dir / "final_trade_decision_report.md").write_text(final_state["final_trade_decision_report"], encoding="utf-8")
        sections.append(f"## IV. Portfolio Management Decision\n\n{final_state['final_trade_decision_report']}")

    # 保存完整报告
    header = f"# Trading Analysis Report: {ticker}\n\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    (save_path / "complete_report.md").write_text(header + "\n\n".join(sections), encoding="utf-8")
    return save_path / "complete_report.md"


# ==================== 页面路由 ====================


@app.route("/")
def index():
    """首页 - 重定向到信号中心。"""
    from flask import redirect
    return redirect("/signals")


@app.route("/signals")
def signals_page():
    """信号中心页面。"""
    return render_template("signals.html")


@app.route("/backtest")
def backtest_page():
    """回测分析页面。"""
    return render_template("backtest.html")


# ==================== API路由 ====================


@app.route("/api/signals")
def api_signals():
    """获取信号列表API。"""
    date = request.args.get("date")
    status = request.args.get("status")
    symbol = request.args.get("symbol")

    recorder = get_recorder()
    signals = recorder.load_signals(
        signal_date=date,
        symbol=symbol,
        execution_status=status,
    )

    return jsonify([s.to_dict() for s in signals])


@app.route("/api/signals/<signal_id>", methods=["GET", "PUT"])
def api_signal_detail(signal_id):
    """单个信号API。"""
    recorder = get_recorder()

    if request.method == "GET":
        record = recorder.load_signal_by_id(signal_id)
        if record is None:
            return jsonify({"error": "信号不存在"}), 404
        return jsonify(record.to_dict())

    elif request.method == "PUT":
        data = request.get_json()
        success = recorder.update_status(
            signal_id=signal_id,
            status=data.get("status", "executed"),
            execution_price=data.get("price"),
            execution_date=data.get("date"),
            actual_quantity=data.get("quantity"),
            notes=data.get("notes", ""),
        )
        if not success:
            return jsonify({"error": "更新失败"}), 400
        return jsonify({"success": True})


@app.route("/api/signals/generate-stream", methods=["POST"])
def api_generate_signals_stream():
    """生成单日信号API（SSE流式版本，实时返回进度和Agent状态）。"""
    data = request.get_json()

    watchlist_path = data.get("watchlist_path", "watchlist.csv")
    trade_date = data.get("date")
    model_config = data.get("model_config", {})
    selected_analysts = model_config.get("selected_analysts", ["market", "news", "fundamentals"])

    # 映射 research_depth 到 max_debate_rounds
    if "research_depth" in model_config:
        model_config["max_debate_rounds"] = model_config["research_depth"]
        model_config["max_risk_discuss_rounds"] = model_config["research_depth"]

    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    def generate():
        try:
            from tradingagents.web.progress_tracker import WebProgressTracker
            from tradingagents.graph.trading_graph import TradingAgentsGraph
            from tradingagents.default_config import DEFAULT_CONFIG
            from tradingagents.signals import SignalRecorder
            from tradingagents.signals.types import TradingSignal
            from tradingagents.agent_core.types import DecisionAction

            watchlist = load_watchlist(watchlist_path)
            tracker = WebProgressTracker(None, selected_analysts=selected_analysts)

            # 合并配置
            config = DEFAULT_CONFIG.copy()
            config.update(model_config)

            # 全局开始时间
            global_start_time = time.time()
            tracker.start_time = global_start_time

            total_symbols = len(watchlist)

            # 发送开始事件
            yield f"event: start\ndata: {json.dumps({'date': trade_date, 'total': total_symbols, 'selected_analysts': selected_analysts})}\n\n"

            # 发送初始agent状态
            yield f"event: agent_status\ndata: {json.dumps(tracker.get_full_status())}\n\n"

            recorder = SignalRecorder()

            # Agent状态更新函数
            ANALYST_ORDER = ["market", "social", "news", "fundamentals"]
            ANALYST_AGENT_NAMES = {
                "market": "Market Analyst",
                "social": "Social Analyst",
                "news": "News Analyst",
                "fundamentals": "Fundamentals Analyst",
            }
            ANALYST_REPORT_MAP = {
                "market": "market_report",
                "social": "sentiment_report",
                "news": "news_report",
                "fundamentals": "fundamentals_report",
            }

            def update_analyst_statuses_from_chunk(chunk, tracker, selected):
                found_active = False
                for analyst_key in ANALYST_ORDER:
                    if analyst_key not in selected:
                        continue
                    agent_name = ANALYST_AGENT_NAMES[analyst_key]
                    report_key = ANALYST_REPORT_MAP[analyst_key]
                    if chunk.get(report_key):
                        tracker.mark_agent_completed(agent_name)
                    elif not found_active:
                        tracker.set_current_agent(agent_name)
                        found_active = True

                if not found_active and selected:
                    all_done = all(
                        tracker.agent_status.get(ANALYST_AGENT_NAMES[key]) == "completed"
                        for key in selected if key in ANALYST_AGENT_NAMES
                    )
                    if all_done and tracker.agent_status.get("Bull Researcher") == "pending":
                        tracker.set_current_agent("Bull Researcher")

            def update_research_team_status(tracker, status):
                for agent in ["Bull Researcher", "Bear Researcher", "Research Manager"]:
                    tracker.agent_status[agent] = status
                tracker._push_event_direct("agent_start", {
                    "agent": "Research Team",
                    "status": status,
                    "agent_status": tracker.agent_status,
                })

            for idx, symbol in enumerate(watchlist, 1):
                # 发送任务开始
                yield f"event: task_start\ndata: {json.dumps({'current': idx, 'total': total_symbols, 'symbol': symbol})}\n\n"

                # 重置统计，保持全局耗时
                tracker.llm_calls = 0
                tracker.tool_calls = 0
                tracker.tokens_in = 0
                tracker.tokens_out = 0
                tracker._init_agent_status()
                tracker.recent_events.clear()
                tracker.current_agent = None
                tracker.start_time = global_start_time

                yield f"event: agent_status\ndata: {json.dumps(tracker.get_full_status())}\n\n"

                try:
                    graph = TradingAgentsGraph(
                        selected_analysts=selected_analysts,
                        config=config,
                        debug=True,
                        callbacks=[tracker],
                    )

                    init_state = graph.propagator.create_initial_state(symbol, trade_date)
                    args = graph.propagator.get_graph_args(callbacks=[tracker])

                    trace = []
                    for chunk in graph.graph.stream(init_state, **args):
                        update_analyst_statuses_from_chunk(chunk, tracker, selected_analysts)

                        # ===== 提取工具调用并发送事件（类似CLI） =====
                        if "messages" in chunk and len(chunk["messages"]) > 0:
                            last_message = chunk["messages"][-1]
                            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                                for tool_call in last_message.tool_calls:
                                    if isinstance(tool_call, dict):
                                        tool_name = tool_call.get("name", "unknown")
                                        tool_args = tool_call.get("args", {})
                                    else:
                                        tool_name = getattr(tool_call, "name", "unknown")
                                        tool_args = getattr(tool_call, "args", {})

                                    # 格式化参数
                                    args_str = str(tool_args)
                                    if len(args_str) > 100:
                                        args_str = args_str[:97] + "..."

                                    # 更新tracker计数
                                    tracker.tool_calls += 1

                                    # 发送tool_start事件
                                    tool_event = {
                                        'tool_name': tool_name,
                                        'args': args_str,
                                        'call_count': tracker.tool_calls,
                                        'timestamp': time.strftime('%H:%M:%S'),
                                        'agent': tracker.current_agent or 'Unknown',
                                    }
                                    yield f"event: tool_start\ndata: {json.dumps(tool_event)}\n\n"
                        # ===== 工具调用提取结束 =====

                        if chunk.get("investment_debate_state"):
                            debate = chunk["investment_debate_state"]
                            if debate.get("bull_history") or debate.get("bear_history"):
                                update_research_team_status(tracker, "in_progress")
                            if debate.get("judge_decision"):
                                update_research_team_status(tracker, "completed")
                                tracker.set_current_agent("Trader")

                        if chunk.get("trader_investment_plan"):
                            tracker.mark_agent_completed("Trader")
                            tracker.set_current_agent("Aggressive Analyst")

                        if chunk.get("risk_debate_state"):
                            risk = chunk["risk_debate_state"]
                            if risk.get("aggressive_history"):
                                tracker.set_current_agent("Aggressive Analyst")
                            if risk.get("conservative_history"):
                                tracker.set_current_agent("Conservative Analyst")
                            if risk.get("neutral_history"):
                                tracker.set_current_agent("Neutral Analyst")
                            if risk.get("judge_decision"):
                                for agent in ["Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"]:
                                    tracker.mark_agent_completed(agent)
                                tracker.set_current_agent("Portfolio Manager")

                        if chunk.get("final_trade_decision_report"):
                            tracker.mark_agent_completed("Portfolio Manager")
                            tracker.mark_agent_completed("Report Finalizer")

                        yield f"event: agent_status\ndata: {json.dumps(tracker.get_full_status())}\n\n"
                        elapsed = int(time.time() - global_start_time)
                        yield f"event: heartbeat\ndata: {json.dumps({'symbol': symbol, 'elapsed': elapsed})}\n\n"

                        trace.append(chunk)

                    final_state = trace[-1]

                    # 保存中间状态到eval_results（与CLI一致）
                    graph.ticker = symbol
                    graph._log_state(trade_date, final_state)

                    # 保存Markdown报告到reports目录（与CLI一致）
                    report_dir = Path("reports") / symbol / trade_date
                    save_report_to_disk(final_state, symbol, report_dir)

                    raw_signal = graph.process_signal(final_state["final_trade_decision"])

                    signal_map = {"BUY": "BUY", "OVERWEIGHT": "BUY", "SELL": "SELL", "UNDERWEIGHT": "SELL", "HOLD": "HOLD"}
                    action_str = signal_map.get((raw_signal or "").upper(), "HOLD")
                    action = DecisionAction(action_str)

                    signal = TradingSignal.create(
                        symbol=symbol,
                        signal_date=trade_date,
                        action=action,
                        rationale=final_state.get("final_trade_decision_report", ""),
                        metadata={"analysts_used": selected_analysts},
                    )
                    recorder.save_signal(signal)

                    yield f"event: task_complete\ndata: {json.dumps({'current': idx, 'total': total_symbols, 'symbol': symbol, 'action': action.value, 'confidence': signal.confidence, 'stats': tracker._get_stats()})}\n\n"

                except Exception as e:
                    yield f"event: task_error\ndata: {json.dumps({'current': idx, 'total': total_symbols, 'symbol': symbol, 'error': str(e)})}\n\n"

            yield f"event: done\ndata: {json.dumps({'date': trade_date, 'count': total_symbols})}\n\n"

        except GeneratorExit:
            print("客户端取消，停止生成")
            return
        except Exception as e:
            yield f"event: fatal_error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/signals/batch-generate-stream", methods=["POST"])
def api_batch_generate_signals_stream():
    """批量生成信号API（SSE流式版本，生成区间内每一天的信号，含详细进度和Agent状态追踪）。"""
    data = request.get_json()

    watchlist_path = data.get("watchlist_path", "watchlist.csv")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    model_config = data.get("model_config", {})
    selected_analysts = model_config.get("selected_analysts", ["market", "news", "fundamentals"])

    # 映射 research_depth 到 max_debate_rounds
    if "research_depth" in model_config:
        model_config["max_debate_rounds"] = model_config["research_depth"]
        model_config["max_risk_discuss_rounds"] = model_config["research_depth"]

    if not start_date or not end_date:
        return jsonify({"error": "需要起始和结束日期"}), 400

    def generate():
        try:
            from datetime import timedelta
            from tradingagents.web.progress_tracker import WebProgressTracker
            from tradingagents.graph.trading_graph import TradingAgentsGraph
            from tradingagents.default_config import DEFAULT_CONFIG
            from tradingagents.signals import SignalRecorder
            from tradingagents.signals.types import TradingSignal
            from tradingagents.agent_core.types import DecisionAction

            watchlist = load_watchlist(watchlist_path)
            tracker = WebProgressTracker(None, selected_analysts=selected_analysts)

            # 合并配置
            config = DEFAULT_CONFIG.copy()
            config.update(model_config)

            # 全局开始时间（不重置）
            global_start_time = time.time()
            tracker.start_time = global_start_time

            # 计算交易日数量
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")

            # 计算总交易日和总任务数
            trading_days = []
            current = start_dt
            while current <= end_dt:
                if current.weekday() < 5:  # 周一到周五
                    trading_days.append(current.strftime("%Y-%m-%d"))
                current += timedelta(days=1)

            total_days = len(trading_days)
            total_symbols = len(watchlist)
            total_tasks = total_days * total_symbols

            # 发送开始事件
            yield f"event: start\ndata: {json.dumps({'start_date': start_date, 'end_date': end_date, 'total_days': total_days, 'total_symbols': total_symbols, 'total_tasks': total_tasks, 'selected_analysts': selected_analysts})}\n\n"

            # 发送初始agent状态
            yield f"event: agent_status\ndata: {json.dumps(tracker.get_full_status())}\n\n"

            completed_tasks = 0
            recorder = SignalRecorder()

            # Agent状态更新函数（类似CLI）
            ANALYST_ORDER = ["market", "social", "news", "fundamentals"]
            ANALYST_AGENT_NAMES = {
                "market": "Market Analyst",
                "social": "Social Analyst",
                "news": "News Analyst",
                "fundamentals": "Fundamentals Analyst",
            }
            ANALYST_REPORT_MAP = {
                "market": "market_report",
                "social": "sentiment_report",
                "news": "news_report",
                "fundamentals": "fundamentals_report",
            }

            def update_analyst_statuses_from_chunk(chunk, tracker, selected):
                """根据chunk更新分析师状态。"""
                found_active = False
                for analyst_key in ANALYST_ORDER:
                    if analyst_key not in selected:
                        continue

                    agent_name = ANALYST_AGENT_NAMES[analyst_key]
                    report_key = ANALYST_REPORT_MAP[analyst_key]

                    has_report = bool(chunk.get(report_key))

                    if has_report:
                        tracker.mark_agent_completed(agent_name)
                    elif not found_active:
                        tracker.set_current_agent(agent_name)
                        found_active = True

                # 如果所有分析师完成，开始研究团队
                if not found_active and selected:
                    all_done = all(
                        tracker.agent_status.get(ANALYST_AGENT_NAMES[key]) == "completed"
                        for key in selected if key in ANALYST_AGENT_NAMES
                    )
                    if all_done and tracker.agent_status.get("Bull Researcher") == "pending":
                        tracker.set_current_agent("Bull Researcher")

            def update_research_team_status(tracker, status):
                """更新研究团队状态。"""
                for agent in ["Bull Researcher", "Bear Researcher", "Research Manager"]:
                    tracker.agent_status[agent] = status
                tracker._push_event_direct("agent_start", {
                    "agent": "Research Team",
                    "status": status,
                    "agent_status": tracker.agent_status,
                })

            for day_idx, trade_date in enumerate(trading_days, 1):
                # 发送日期进度
                yield f"event: day\ndata: {json.dumps({'day_current': day_idx, 'day_total': total_days, 'date': trade_date})}\n\n"

                for symbol_idx, symbol in enumerate(watchlist, 1):
                    completed_tasks += 1
                    task_idx = (day_idx - 1) * total_symbols + symbol_idx

                    # 发送任务开始
                    yield f"event: task_start\ndata: {json.dumps({'task_current': task_idx, 'task_total': total_tasks, 'day': day_idx, 'symbol': symbol})}\n\n"

                    # 重置每个任务的统计，保持全局耗时
                    tracker.llm_calls = 0
                    tracker.tool_calls = 0
                    tracker.tokens_in = 0
                    tracker.tokens_out = 0
                    tracker._init_agent_status()
                    tracker.recent_events.clear()
                    tracker.current_agent = None
                    tracker.start_time = global_start_time

                    # 发送初始状态
                    yield f"event: agent_status\ndata: {json.dumps(tracker.get_full_status())}\n\n"

                    try:
                        # 创建图（使用debug=True启用流式）
                        graph = TradingAgentsGraph(
                            selected_analysts=selected_analysts,
                            config=config,
                            debug=True,
                            callbacks=[tracker],
                        )

                        # 初始化状态
                        init_state = graph.propagator.create_initial_state(symbol, trade_date)
                        args = graph.propagator.get_graph_args(callbacks=[tracker])

                        # 流式执行，分析每个chunk
                        trace = []
                        for chunk in graph.graph.stream(init_state, **args):
                            # 更新分析师状态
                            update_analyst_statuses_from_chunk(chunk, tracker, selected_analysts)

                            # ===== 提取工具调用并发送事件（类似CLI） =====
                            if "messages" in chunk and len(chunk["messages"]) > 0:
                                last_message = chunk["messages"][-1]
                                if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                                    for tool_call in last_message.tool_calls:
                                        if isinstance(tool_call, dict):
                                            tool_name = tool_call.get("name", "unknown")
                                            tool_args = tool_call.get("args", {})
                                        else:
                                            tool_name = getattr(tool_call, "name", "unknown")
                                            tool_args = getattr(tool_call, "args", {})

                                        # 格式化参数
                                        args_str = str(tool_args)
                                        if len(args_str) > 100:
                                            args_str = args_str[:97] + "..."

                                        # 更新tracker计数
                                        tracker.tool_calls += 1

                                        # 发送tool_start事件
                                        tool_event = {
                                            'tool_name': tool_name,
                                            'args': args_str,
                                            'call_count': tracker.tool_calls,
                                            'timestamp': time.strftime('%H:%M:%S'),
                                            'agent': tracker.current_agent or 'Unknown',
                                        }
                                        yield f"event: tool_start\ndata: {json.dumps(tool_event)}\n\n"
                            # ===== 工具调用提取结束 =====

                            # 研究团队状态
                            if chunk.get("investment_debate_state"):
                                debate = chunk["investment_debate_state"]
                                if debate.get("bull_history") or debate.get("bear_history"):
                                    update_research_team_status(tracker, "in_progress")
                                if debate.get("judge_decision"):
                                    update_research_team_status(tracker, "completed")
                                    tracker.set_current_agent("Trader")

                            # 交易团队
                            if chunk.get("trader_investment_plan"):
                                tracker.mark_agent_completed("Trader")
                                tracker.set_current_agent("Aggressive Analyst")

                            # 风险管理
                            if chunk.get("risk_debate_state"):
                                risk = chunk["risk_debate_state"]
                                if risk.get("aggressive_history"):
                                    tracker.set_current_agent("Aggressive Analyst")
                                if risk.get("conservative_history"):
                                    tracker.set_current_agent("Conservative Analyst")
                                if risk.get("neutral_history"):
                                    tracker.set_current_agent("Neutral Analyst")
                                if risk.get("judge_decision"):
                                    for agent in ["Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"]:
                                        tracker.mark_agent_completed(agent)
                                    tracker.set_current_agent("Portfolio Manager")

                            # 最终报告
                            if chunk.get("final_trade_decision_report"):
                                tracker.mark_agent_completed("Portfolio Manager")
                                tracker.mark_agent_completed("Report Finalizer")

                            # 发送状态更新事件
                            yield f"event: agent_status\ndata: {json.dumps(tracker.get_full_status())}\n\n"

                            # 发送心跳（保持耗时显示）
                            elapsed = int(time.time() - global_start_time)
                            yield f"event: heartbeat\ndata: {json.dumps({'symbol': symbol, 'elapsed': elapsed})}\n\n"

                            trace.append(chunk)

                        # 获取最终状态和决策
                        final_state = trace[-1]

                        # 保存中间状态到eval_results（与CLI一致）
                        graph.ticker = symbol
                        graph._log_state(trade_date, final_state)

                        # 保存Markdown报告到reports目录（与CLI一致）
                        report_dir = Path("reports") / symbol / trade_date
                        save_report_to_disk(final_state, symbol, report_dir)

                        raw_signal = graph.process_signal(final_state["final_trade_decision"])

                        # 映射到DecisionAction
                        signal_map = {"BUY": "BUY", "OVERWEIGHT": "BUY", "SELL": "SELL", "UNDERWEIGHT": "SELL", "HOLD": "HOLD"}
                        action_str = signal_map.get((raw_signal or "").upper(), "HOLD")
                        action = DecisionAction(action_str)

                        # 创建并保存信号
                        signal = TradingSignal.create(
                            symbol=symbol,
                            signal_date=trade_date,
                            action=action,
                            rationale=final_state.get("final_trade_decision_report", ""),
                            metadata={"analysts_used": selected_analysts},
                        )
                        recorder.save_signal(signal)

                        yield f"event: task_complete\ndata: {json.dumps({'task_current': task_idx, 'task_total': total_tasks, 'day': day_idx, 'symbol': symbol, 'action': action.value, 'confidence': signal.confidence, 'stats': tracker._get_stats()})}\n\n"

                    except Exception as e:
                        yield f"event: task_error\ndata: {json.dumps({'task_current': task_idx, 'task_total': total_tasks, 'day': day_idx, 'symbol': symbol, 'error': str(e), 'stats': tracker._get_stats()})}\n\n"

            # 发送完成事件
            yield f"event: done\ndata: {json.dumps({'start_date': start_date, 'end_date': end_date, 'total_days': total_days, 'total_signals': completed_tasks})}\n\n"

        except GeneratorExit:
            print("客户端取消，停止生成")
            return
        except Exception as e:
            yield f"event: fatal_error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/portfolio")
def api_portfolio():
    """获取组合状态API。"""
    tracker = get_tracker()
    summary = tracker.get_positions_summary()
    return jsonify(summary)


@app.route("/api/portfolio/buy", methods=["POST"])
def api_portfolio_buy():
    """买入操作API。"""
    tracker = get_tracker()
    data = request.get_json()

    try:
        position = tracker.buy(
            symbol=data["symbol"],
            quantity=int(data["quantity"]),
            price=float(data["price"]),
            date=data.get("date", ""),
            notes=data.get("notes", ""),
        )
        tracker.save_snapshot(data.get("date"))
        return jsonify({"success": True, "position": position.to_dict()})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/portfolio/sell", methods=["POST"])
def api_portfolio_sell():
    """卖出操作API。"""
    tracker = get_tracker()
    data = request.get_json()

    try:
        pnl = tracker.sell(
            symbol=data["symbol"],
            quantity=int(data.get("quantity") or 0) if data.get("quantity") else None,
            price=float(data["price"]),
            date=data.get("date", ""),
            notes=data.get("notes", ""),
        )
        tracker.save_snapshot(data.get("date"))
        return jsonify({"success": True, "realized_pnl": pnl})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/portfolio/equity_curve")
def api_equity_curve():
    """获取权益曲线API。"""
    tracker = get_tracker()
    curve = tracker.get_equity_curve()
    return jsonify(curve)


@app.route("/api/portfolio/reset", methods=["POST"])
def api_portfolio_reset():
    """重置组合API。"""
    tracker = get_tracker()
    tracker.reset()
    return jsonify({"success": True})


@app.route("/api/statistics")
def api_statistics():
    """获取统计信息API。"""
    recorder = get_recorder()
    start = request.args.get("start")
    end = request.args.get("end")
    stats = recorder.get_statistics(start_date=start, end_date=end)
    return jsonify(stats)


# ==================== 回测API ====================


def parse_csv_to_df(csv_str: str) -> pd.DataFrame:
    """解析CSV字符串为DataFrame。"""
    lines = csv_str.strip().split('\n')
    data_lines = [l for l in lines if l and not l.startswith('#')]
    if not data_lines:
        return pd.DataFrame()

    header = data_lines[0].split(',')
    data = []
    for line in data_lines[1:]:
        if line:
            row = line.split(',')
            if len(row) == len(header):
                data.append(row)

    df = pd.DataFrame(data, columns=header)

    numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount', 'PctChange', 'TurnoverPct']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')
        df = df.sort_index()

    return df


@app.route("/api/backtest/run", methods=["POST"])
def api_backtest_run():
    """执行回测API。"""
    data = request.get_json()

    start_date = data.get("start_date")
    end_date = data.get("end_date")
    initial_capital = float(data.get("capital", 100000))
    max_position_pct = float(data.get("max_position_pct", 0.2))
    max_positions = int(data.get("max_positions", 5))
    buy_amount_pct = float(data.get("buy_amount_pct", 0.1))
    commission_rate = float(data.get("commission_rate", 0.0003))
    stamp_duty_rate = float(data.get("stamp_duty_rate", 0.0005))

    if not start_date or not end_date:
        return jsonify({"error": "需要起始和结束日期"}), 400

    try:
        # 1. 加载信号
        recorder = get_recorder()
        records = recorder.load_signals(start_date=start_date, end_date=end_date)

        decisions = []
        for record in records:
            signal = record.signal
            if signal.action == DecisionAction.HOLD:
                continue

            decision = AgentDecision(
                agent_name=signal.metadata.get("agent_name", "tradingagents"),
                symbol=signal.symbol,
                trade_date=signal.signal_date,
                action=signal.action,
                quantity=signal.suggested_quantity or 100,
                holding_period_bars=signal.metadata.get("holding_period_bars", 5),
            )
            decisions.append(decision)

        if not decisions:
            return jsonify({"error": "无可用信号"}), 400

        # 2. 获取日线数据
        symbols = list(set(d.symbol for d in decisions))
        daily_data_map = {}

        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        extended_end = (end_dt + timedelta(days=30)).strftime("%Y-%m-%d")

        for symbol in symbols:
            try:
                csv_str = get_stock_data(symbol, start_date, extended_end)
                df = parse_csv_to_df(csv_str)
                if not df.empty:
                    daily_data_map[symbol] = df
            except Exception:
                pass

        if not daily_data_map:
            return jsonify({"error": "无法获取日线数据"}), 400

        # 3. 执行回测
        cost_config = TransactionCostConfig(
            commission_rate=commission_rate,
            stamp_duty_rate=stamp_duty_rate,
        )

        engine = PortfolioBacktestEngine(
            initial_capital=initial_capital,
            cost_config=cost_config,
            max_position_pct=max_position_pct,
            max_positions=max_positions,
            buy_amount_pct=buy_amount_pct,
        )

        report = engine.backtest_decisions(decisions, daily_data_map)

        # 4. 保存报告
        reports_dir = Path("backtest_results")
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / f"{start_date}_{end_date}.json"

        report_data = {
            "start_date": report.start_date,
            "end_date": report.end_date,
            "initial_capital": report.initial_capital,
            "final_equity": report.final_equity,
            "total_return": report.total_return,
            "annualized_return": report.annualized_return,
            "annualized_volatility": report.annualized_volatility,
            "sharpe_ratio": report.sharpe_ratio,
            "sortino_ratio": report.sortino_ratio,
            "max_drawdown": report.max_drawdown,
            "max_drawdown_duration": report.max_drawdown_duration,
            "total_trades": report.total_trades,
            "win_rate": report.win_rate,
            "profit_factor": report.profit_factor,
            "avg_win_pct": report.avg_win_pct,
            "avg_loss_pct": report.avg_loss_pct,
            "avg_holding_days": report.avg_holding_days,
            "total_commission": report.total_commission,
            "total_stamp_duty": report.total_stamp_duty,
            "total_transfer_fee": report.total_transfer_fee,
            "total_costs": report.total_costs,
            "equity_curve": [{"date": d, "equity": e} for d, e in report.equity_curve],
            "trades": [
                {
                    "symbol": t.symbol,
                    "trade_date": t.trade_date,
                    "action": t.action,
                    "executed": t.executed,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "return_pct": t.return_pct,
                    "pnl": t.pnl,
                    "notes": t.notes,
                }
                for t in report.trades
            ],
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        return jsonify({
            "success": True,
            "report": report_data,
            "saved_to": str(report_path),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/backtest/report/<filename>")
def api_backtest_report(filename):
    """获取已保存的回测报告。"""
    report_path = Path("backtest_results") / filename
    if not report_path.exists():
        return jsonify({"error": "报告不存在"}), 404

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/backtest/reports")
def api_backtest_reports():
    """获取所有已保存的回测报告列表。"""
    reports_dir = Path("backtest_results")
    if not reports_dir.exists():
        return jsonify([])

    reports = []
    for f in reports_dir.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                reports.append({
                    "filename": f.name,
                    "start_date": data.get("start_date"),
                    "end_date": data.get("end_date"),
                    "total_return": data.get("total_return"),
                    "sharpe_ratio": data.get("sharpe_ratio"),
                    "win_rate": data.get("win_rate"),
                })
        except Exception:
            pass

    reports.sort(key=lambda r: r.get("start_date", ""), reverse=True)
    return jsonify(reports)


# ==================== 启动函数 ====================


def run_server(host: str = "0.0.0.0", port: int = 5000, debug: bool = False):
    """启动Web服务器。"""
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_server(debug=True)