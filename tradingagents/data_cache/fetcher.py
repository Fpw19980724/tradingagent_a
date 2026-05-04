"""数据获取与缓存集成模块。"""

from datetime import datetime, timedelta
from typing import Any, Optional, List, Dict, Tuple

import pandas as pd

from tradingagents.data_cache import get_db, DataCacheDB


class CachedDataFetcher:
    """带缓存的数据获取器 - 自动将获取的数据存入数据库。"""

    def __init__(self, db: Optional[DataCacheDB] = None):
        """
        初始化缓存数据获取器。

        参数：
            db: 数据库实例，默认使用全局实例。
        """
        self.db = db or get_db()

    def fetch_news_with_cache(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        force: bool = False,
    ) -> Tuple[str, bool]:
        """
        获取新闻数据（带缓存）。

        参数：
            symbol: 股票代码。
            start_date: 开始日期。
            end_date: 结束日期。
            force: 是否强制获取（忽略缓存）。

        返回：
            tuple: (新闻数据字符串, 是否有新数据)
        """
        from tradingagents.dataflows.a_share import get_news as fetch_news_api

        # 检查是否需要获取
        if not force:
            latest_time = self.db.get_latest_news_time(symbol)
            if latest_time:
                latest_date = latest_time.split()[0] if ' ' in latest_time else latest_time
                if end_date <= latest_date:
                    # 数据库已有数据，从缓存读取并返回
                    cached_news = self._get_cached_news(symbol, start_date, end_date)
                    return cached_news, False

        # 获取新闻
        news_str = fetch_news_api(symbol, start_date, end_date)

        # 解析并存储到数据库
        if news_str and "未找到" not in news_str:
            news_list = self._parse_news_data(news_str, symbol)
            new_count = self.db.save_news(symbol, news_list)
            return news_str, new_count > 0

        return news_str, False

    def _get_cached_news(self, symbol: str, start_date: str, end_date: str) -> str:
        """从数据库读取缓存的新闻数据并格式化。"""
        import sqlite3

        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT publish_time, source, title, content, url
            FROM news
            WHERE symbol = ?
            AND publish_time >= ?
            AND publish_time <= ?
            ORDER BY publish_time DESC
        """, (symbol, start_date, end_date + " 23:59:59"))

        rows = cursor.fetchall()
        if not rows:
            return ""

        # 格式化为CSV格式（与API返回格式一致）
        lines = ["# 发布时间,来源,标题,内容,URL"]
        for row in rows:
            lines.append(f"{row[0]},{row[1]},{row[2]},{row[3]},{row[4]}")

        return "\n".join(lines)

    def fetch_announcements_with_cache(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        category: str = "全部",
        force: bool = False,
    ) -> Tuple[str, bool]:
        """
        获取公告数据（带缓存）。

        返回：
            tuple: (公告数据字符串, 是否有新数据)
        """
        from tradingagents.dataflows.a_share import get_company_announcements as fetch_ann_api

        if not force:
            latest = self.db.get_latest_announcement_date(symbol)
            if latest and end_date <= latest:
                # 从缓存读取
                cached_ann = self._get_cached_announcements(symbol, start_date, end_date, category)
                return cached_ann, False

        ann_str = fetch_ann_api(symbol, start_date, end_date, category)

        if ann_str and "没有匹配" not in ann_str:
            ann_list = self._parse_announcements_data(ann_str, symbol)
            new_count = self.db.save_announcements(symbol, ann_list)
            return ann_str, new_count > 0

        return ann_str, False

    def _get_cached_announcements(self, symbol: str, start_date: str, end_date: str, category: str) -> str:
        """从数据库读取缓存的公告数据并格式化。"""
        import sqlite3

        cursor = self.db.conn.cursor()

        if category == "全部":
            cursor.execute("""
                SELECT publish_date, type, title, url
                FROM announcements
                WHERE symbol = ?
                AND publish_date >= ?
                AND publish_date <= ?
                ORDER BY publish_date DESC
            """, (symbol, start_date, end_date))
        else:
            cursor.execute("""
                SELECT publish_date, type, title, url
                FROM announcements
                WHERE symbol = ?
                AND publish_date >= ?
                AND publish_date <= ?
                AND type = ?
                ORDER BY publish_date DESC
            """, (symbol, start_date, end_date, category))

        rows = cursor.fetchall()
        if not rows:
            return ""

        # 格式化为CSV格式
        lines = ["# 公告日期,公告类型,公告标题,公告链接"]
        for row in rows:
            lines.append(f"{row[0]},{row[1]},{row[2]},{row[3]}")

        return "\n".join(lines)

    def fetch_financials_with_cache(
        self,
        symbol: str,
        report_type: str,
        report_date: str,
        force: bool = False,
    ) -> Tuple[str, bool]:
        """
        获取财务报表（带缓存）。

        参数：
            symbol: 股票代码。
            report_type: 报表类型 ('fundamentals', 'balance_sheet', 'income', 'cashflow')。
            report_date: 报告日期。
            force: 是否强制获取。

        返回：
            tuple: (数据字符串, 是否是新数据)
        """
        # 检查缓存
        if not force:
            cached = self.db.get_financial_report(symbol, report_type, report_date)
            if cached:
                # 从缓存返回
                return self._format_cached_financial(cached), False

        # 获取新数据 - 调用实际API
        if report_type == 'fundamentals':
            from tradingagents.dataflows.a_share import get_fundamentals as fetch_api
            data_str = fetch_api(symbol)
        elif report_type == 'balance_sheet':
            from tradingagents.dataflows.a_share import get_balance_sheet as fetch_api
            data_str = fetch_api(symbol)
        elif report_type == 'income':
            from tradingagents.dataflows.a_share import get_income_statement as fetch_api
            data_str = fetch_api(symbol)
        elif report_type == 'cashflow':
            from tradingagents.dataflows.a_share import get_cashflow as fetch_api
            data_str = fetch_api(symbol)
        else:
            data_str = ""

        # 存储到数据库
        if data_str:
            self.db.save_financial_report(
                symbol=symbol,
                report_type=report_type,
                report_date=report_date,
                data={'raw': data_str},
            )
            return data_str, True

        return data_str, False

    def check_all_updates(
        self,
        symbol: str,
        trade_date: str,
    ) -> Dict[str, Dict]:
        """
        检查所有数据源的更新状态。

        返回：
            dict: 各数据源的更新状态和理由。
        """
        # 计算查询日期范围
        end_date = trade_date
        start_date = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")

        results = {}

        # 新闻
        news_str, has_new_news = self.fetch_news_with_cache(symbol, start_date, end_date)
        results['news'] = {
            'has_new': has_new_news,
            'data': news_str if has_new_news else "",
        }

        # 公告
        ann_start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d")
        ann_str, has_new_ann = self.fetch_announcements_with_cache(symbol, ann_start, end_date)
        results['announcements'] = {
            'has_new': has_new_ann,
            'data': ann_str if has_new_ann else "",
        }

        # 财务数据 - 使用最新季度
        quarter_date = self._get_latest_quarter_date(trade_date)
        fin_str, has_new_fin = self.fetch_financials_with_cache(symbol, 'fundamentals', quarter_date)
        results['fundamentals'] = {
            'has_new': has_new_fin,
            'data': fin_str if has_new_fin else "",
        }

        return results

    def _parse_news_data(self, news_str: str, symbol: str) -> List[Dict]:
        """解析新闻CSV数据为字典列表。"""
        lines = news_str.strip().split('\n')
        news_list = []

        for line in lines:
            if line.startswith('#') or not line or '发布时间' in line:
                continue

            parts = line.split(',')
            if len(parts) >= 5:
                news_list.append({
                    'symbol': symbol,
                    'publish_time': parts[0] if parts[0] else '',
                    'source': parts[1] if len(parts) > 1 else '',
                    'title': parts[2] if len(parts) > 2 else '',
                    'content': parts[3] if len(parts) > 3 else '',
                    'url': parts[4] if len(parts) > 4 else '',
                })

        return news_list

    def _parse_announcements_data(self, ann_str: str, symbol: str) -> List[Dict]:
        """解析公告CSV数据。"""
        lines = ann_str.strip().split('\n')
        ann_list = []

        for line in lines:
            if line.startswith('#') or not line or '公告日期' in line:
                continue

            parts = line.split(',')
            if len(parts) >= 4:
                ann_list.append({
                    'symbol': symbol,
                    'publish_date': parts[0] if parts[0] else '',
                    'type': parts[1] if len(parts) > 1 else '',
                    'title': parts[2] if len(parts) > 2 else '',
                    'url': parts[3] if len(parts) > 3 else '',
                })

        return ann_list

    def _get_latest_quarter_date(self, trade_date: str) -> str:
        """获取最近的季度报告日期。"""
        date = datetime.strptime(trade_date, "%Y-%m-%d")
        year = date.year
        month = date.month

        # 季度报告通常是3月、6月、9月、12月
        if month < 5:
            return f"{year-1}1231"  # 去年年报
        elif month < 8:
            return f"{year}0331"    # 今年一季报
        elif month < 11:
            return f"{year}0630"    # 今年半年报
        else:
            return f"{year}0930"    # 今年三季报

    def _format_cached_financial(self, cached_data: Dict) -> str:
        """格式化缓存的财务数据。"""
        return cached_data.get('raw', "")


# 全局实例（支持不同db_path）
_fetcher_instances: Dict[str, CachedDataFetcher] = {}


def get_fetcher(db_path: str = "data_cache.db") -> CachedDataFetcher:
    """获取数据获取器实例。"""
    global _fetcher_instances
    if db_path not in _fetcher_instances:
        _fetcher_instances[db_path] = CachedDataFetcher(get_db(db_path))
    return _fetcher_instances[db_path]