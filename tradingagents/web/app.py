"""Web Dashboard - Flask应用。"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template, request

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


# ==================== 页面路由 ====================


@app.route("/")
def dashboard():
    """仪表盘首页。"""
    recorder = get_recorder()
    tracker = get_tracker()

    stats = recorder.get_statistics()
    portfolio = tracker.get_positions_summary()

    return render_template(
        "dashboard.html",
        stats=stats,
        portfolio=portfolio,
    )


@app.route("/signals")
def signals_page():
    """信号列表页面。"""
    date = request.args.get("date")
    status = request.args.get("status")
    symbol = request.args.get("symbol")

    recorder = get_recorder()
    signals = recorder.load_signals(
        signal_date=date,
        symbol=symbol,
        execution_status=status,
    )

    return render_template(
        "signals.html",
        signals=signals,
        filters={"date": date, "status": status, "symbol": symbol},
    )


@app.route("/portfolio")
def portfolio_page():
    """组合状态页面。"""
    tracker = get_tracker()
    summary = tracker.get_positions_summary()
    equity_curve = tracker.get_equity_curve()

    return render_template(
        "portfolio.html",
        portfolio=summary,
        equity_curve=equity_curve,
    )


@app.route("/backtest")
def backtest_page():
    """回测页面。"""
    recorder = get_recorder()
    stats = recorder.get_statistics()

    # 检查是否有历史报告
    reports_dir = Path("backtest_results")
    saved_reports = []
    if reports_dir.exists():
        for f in reports_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    saved_reports.append({
                        "filename": f.name,
                        "start_date": data.get("start_date"),
                        "end_date": data.get("end_date"),
                        "total_return": data.get("total_return"),
                        "sharpe_ratio": data.get("sharpe_ratio"),
                    })
            except Exception:
                pass

    return render_template(
        "backtest.html",
        stats=stats,
        saved_reports=saved_reports,
    )


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


@app.route("/api/signals/generate", methods=["POST"])
def api_generate_signals():
    """生成信号API。"""
    data = request.get_json()

    watchlist_path = data.get("watchlist_path", "watchlist.csv")
    trade_date = data.get("date")

    if not trade_date:
        from datetime import datetime
        trade_date = datetime.now().strftime("%Y-%m-%d")

    try:
        watchlist = load_watchlist(watchlist_path)
        generator = SignalGenerator()
        signals = generator.generate_and_save(watchlist, trade_date)

        return jsonify({
            "success": True,
            "date": trade_date,
            "count": len(signals),
            "signals": [{"id": s.signal_id, "symbol": s.symbol, "action": s.action.value} for s in signals],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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