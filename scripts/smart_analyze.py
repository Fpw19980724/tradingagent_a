#!/usr/bin/env python3
"""智能分析触发器 - 根据数据更新状态决定是否运行分析。"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

from tradingagents.data_cache import get_db, get_fetcher, DataCacheDB, CachedDataFetcher
from tradingagents.signals import SignalGenerator, SignalRecorder, load_watchlist
from tradingagents.agent_core.types import DecisionAction


class SmartAnalyzer:
    """智能分析器 - 检查数据更新状态，决定是否运行分析。"""

    def __init__(
        self,
        db_path: str = "data_cache.db",
        signals_dir: str = "signals",
        watchlist_path: str = "watchlist.csv",
        config: Optional[Dict] = None,
    ):
        """
        初始化智能分析器。

        参数：
            db_path: 数据库路径。
            signals_dir: 信号存储目录。
            watchlist_path: 关注列表路径。
            config: 运行配置。
        """
        self.db = get_db(db_path)
        self.fetcher = get_fetcher(db_path)
        self.generator = SignalGenerator(
            signal_storage_dir=signals_dir,
            config=config,
        )
        self.recorder = SignalRecorder(storage_dir=signals_dir)
        self.watchlist_path = watchlist_path

    def close(self):
        """关闭数据库连接。"""
        self.db.close()

    def check_data_updates(self, symbol: str, trade_date: str) -> Dict:
        """
        检查各数据源的更新状态。

        返回：
            dict: {
                'market': True/False,
                'news': True/False,
                'fundamentals': True/False,
                'social': True/False,
                'reasons': {...}
            }
        """
        result = {
            'market': True,  # 技术数据每日更新
            'reasons': {}
        }

        # 获取上次分析日期
        last_analyze = self.db.get_last_analysis_date(symbol)

        # 检查新闻更新
        news_status = self._check_news_update(symbol, trade_date, last_analyze)
        result['news'] = news_status['needs_update']
        result['reasons']['news'] = news_status['reason']

        # 检查公告更新
        ann_status = self._check_announcements_update(symbol, trade_date, last_analyze)
        result['announcements'] = ann_status['needs_update']
        result['reasons']['announcements'] = ann_status['reason']

        # 检查财务数据更新（季度）
        fin_status = self._check_financials_update(symbol)
        result['fundamentals'] = fin_status['needs_update']
        result['reasons']['fundamentals'] = fin_status['reason']

        # 社交舆情（默认需要，因为没有独立数据源）
        result['social'] = result['news']  # 与新闻同步

        return result

    def _check_news_update(
        self,
        symbol: str,
        trade_date: str,
        last_analyze_date: Optional[str],
    ) -> Dict:
        """检查新闻更新状态。"""
        # 检查数据库中最新新闻时间
        latest_news_time = self.db.get_latest_news_time(symbol)

        if latest_news_time is None:
            return {'needs_update': True, 'reason': '数据库无新闻数据'}

        # 比较日期
        latest_date = latest_news_time.split()[0] if ' ' in latest_news_time else latest_news_time

        if trade_date > latest_date:
            return {
                'needs_update': True,
                'reason': f'有新日期的新闻 ({trade_date} > {latest_date})'
            }

        # 检查上次分析距今的天数
        if last_analyze_date:
            last_date = datetime.strptime(last_analyze_date, "%Y-%m-%d")
            days_since = (datetime.now() - last_date).days
            if days_since > 3:
                return {
                    'needs_update': True,
                    'reason': f'距上次分析已{days_since}天'
                }

        return {'needs_update': False, 'reason': '无新新闻'}

    def _check_announcements_update(
        self,
        symbol: str,
        trade_date: str,
        last_analyze_date: Optional[str],
    ) -> Dict:
        """检查公告更新状态。"""
        latest_ann = self.db.get_latest_announcement_date(symbol)

        if latest_ann is None:
            return {'needs_update': True, 'reason': '数据库无公告数据'}

        if trade_date > latest_ann:
            return {
                'needs_update': True,
                'reason': f'有新日期的公告 ({trade_date} > {latest_ann})'
            }

        # 公告频率较低，检查间隔可以更长
        if last_analyze_date:
            last_date = datetime.strptime(last_analyze_date, "%Y-%m-%d")
            days_since = (datetime.now() - last_date).days
            if days_since > 7:
                return {
                    'needs_update': True,
                    'reason': f'距上次分析已{days_since}天'
                }

        return {'needs_update': False, 'reason': '无新公告'}

    def _check_financials_update(self, symbol: str) -> Dict:
        """检查财务数据更新状态（季度）。"""
        latest_financial = self.db.get_latest_financial_date(symbol, 'balance_sheet')

        if latest_financial is None:
            return {'needs_update': True, 'reason': '数据库无财务数据'}

        # 财务报表是季度发布
        try:
            last_date = datetime.strptime(latest_financial, "%Y%m%d")
            days_since = (datetime.now() - last_date).days

            # 季度报表通常间隔90天左右
            if days_since > 90:
                return {
                    'needs_update': True,
                    'reason': f'财务数据已过期{days_since}天'
                }

            return {'needs_update': False, 'reason': '财务数据在有效期内'}
        except Exception:
            return {'needs_update': True, 'reason': '日期格式异常'}

    def analyze_single(
        self,
        symbol: str,
        trade_date: str,
        force: bool = False,
    ) -> Dict:
        """
        智能分析单只股票。

        参数：
            symbol: 股票代码。
            trade_date: 交易日期。
            force: 是否强制运行（忽略数据更新检查）。

        返回：
            dict: 分析结果。
        """
        # 检查数据更新状态
        if force:
            status = {
                'market': True,
                'news': True,
                'fundamentals': True,
                'social': True,
                'reasons': {'all': '强制运行模式'}
            }
            selected_analysts = None  # 使用默认分析师
        else:
            status = self.check_data_updates(symbol, trade_date)

            # 根据更新状态选择分析师
            selected_analysts = []
            if status['market']:
                selected_analysts.append('market')
            if status['news'] or status['announcements']:
                selected_analysts.append('news')
            if status['fundamentals']:
                selected_analysts.append('fundamentals')

            # 至少运行市场分析
            if not selected_analysts:
                selected_analysts = ['market']

        # 判断是否需要运行分析
        needs_any_update = any([
            status['market'],
            status['news'],
            status['fundamentals'],
        ])

        if not needs_any_update and not force:
            # 无需更新，返回上次分析结果
            last_result = self.db.get_analysis(symbol, trade_date)
            if last_result:
                return {
                    'symbol': symbol,
                    'trade_date': trade_date,
                    'status': 'skipped',
                    'reason': '无数据更新，使用上次分析结果',
                    'last_analysis': last_result,
                }

        print(f"\n{symbol} 数据更新状态:")
        for agent, needed in status.items():
            if agent != 'reasons':
                reason = status['reasons'].get(agent, '')
                print(f"  {agent}: {'需要更新' if needed else '无需更新'} - {reason}")

        print(f"  运行分析师: {', '.join(selected_analysts)}")

        # 预获取数据并存入缓存
        pre_fetch_status = self.generator._pre_fetch_data(symbol, trade_date, selected_analysts)

        # 执行分析（只运行需要的分析师）
        signal = self.generator.generate_for_symbol(
            symbol,
            trade_date,
            selected_analysts=selected_analysts,
            pre_fetch_data=False,  # 已预获取
        )

        # 保存分析结果到数据库
        self.db.save_analysis(
            symbol=symbol,
            analyze_date=trade_date,
            action=signal.action.value,
            rationale=signal.rationale,
            confidence=signal.confidence,
            agents_used=selected_analysts,
        )

        return {
            'symbol': symbol,
            'trade_date': trade_date,
            'status': 'analyzed',
            'signal': signal,
            'agents_used': selected_analysts,
            'update_status': status,
            'pre_fetch_status': pre_fetch_status,
        }

    def analyze_watchlist(
        self,
        trade_date: str,
        force: bool = False,
        save_signals: bool = True,
    ) -> List[Dict]:
        """
        批量智能分析关注列表。

        参数：
            trade_date: 交易日期。
            force: 是否强制运行。
            save_signals: 是否保存信号到文件。

        返回：
            list: 各股票的分析结果。
        """
        watchlist = load_watchlist(self.watchlist_path)
        results = []

        print(f"\n智能分析关注列表 ({len(watchlist)} 只股票)")
        print(f"日期: {trade_date}")
        print("=" * 60)

        for symbol in watchlist:
            result = self.analyze_single(symbol, trade_date, force=force)
            results.append(result)

            if save_signals and result['status'] == 'analyzed':
                self.recorder.save_signal(result['signal'])

        # 统计
        analyzed = sum(1 for r in results if r['status'] == 'analyzed')
        skipped = sum(1 for r in results if r['status'] == 'skipped')

        print("\n" + "=" * 60)
        print(f"分析完成: {analyzed} 只需要更新, {skipped} 只跳过")

        # 打印分析结果摘要
        for r in results:
            if r['status'] == 'analyzed':
                sig = r['signal']
                print(f"  {sig.symbol}: {sig.action.value}")
            elif r['status'] == 'skipped':
                print(f"  {r['symbol']}: 跳过 - {r['reason']}")

        return results

    def get_summary(self) -> Dict:
        """获取数据库统计摘要。"""
        stats = self.db.get_statistics()

        # 获取过期数据统计
        stale_news = self.db.get_stale_symbols('news', max_age_days=7)
        stale_ann = self.db.get_stale_symbols('announcements', max_age_days=14)

        return {
            'news_count': stats['news_count'],
            'announcements_count': stats['announcements_count'],
            'analysis_count': stats['analysis_count'],
            'stale_news_symbols': stale_news,
            'stale_announcements_symbols': stale_ann,
        }


def main():
    parser = argparse.ArgumentParser(description="智能分析触发器")

    parser.add_argument(
        "--date",
        "-d",
        type=str,
        default=None,
        help="交易日期",
    )
    parser.add_argument(
        "--watchlist",
        "-w",
        type=str,
        default="watchlist.csv",
        help="关注列表文件",
    )
    parser.add_argument(
        "--symbol",
        "-s",
        type=str,
        default=None,
        help="单个股票代码",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="强制运行（忽略数据更新检查）",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="只显示数据状态，不运行分析",
    )

    args = parser.parse_args()

    if args.date is None:
        args.date = datetime.now().strftime("%Y-%m-%d")

    analyzer = SmartAnalyzer(
        watchlist_path=args.watchlist,
    )

    try:
        if args.status:
            # 显示数据状态
            summary = analyzer.get_summary()
            print("\n数据库统计:")
            print(f"  新闻条数: {summary['news_count']}")
            print(f"  公告条数: {summary['announcements_count']}")
            print(f"  分析记录: {summary['analysis_count']}")
            print(f"  新闻过期股票: {len(summary['stale_news_symbols'])}")
            print(f"  公告过期股票: {len(summary['stale_announcements_symbols'])}")

        elif args.symbol:
            # 分析单只股票
            result = analyzer.analyze_single(args.symbol, args.date, force=args.force)
            print("\n分析结果:")
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

        else:
            # 批量分析
            analyzer.analyze_watchlist(args.date, force=args.force)

    finally:
        analyzer.close()


if __name__ == "__main__":
    main()