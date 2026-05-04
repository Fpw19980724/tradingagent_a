"""数据库管理模块 - 用于缓存资讯数据和判断是否需要更新。"""

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, List, Dict


class DataCacheDB:
    """资讯数据缓存数据库。"""

    def __init__(self, db_path: str = "data_cache.db"):
        """
        初始化数据库连接。

        参数：
            db_path: 数据库文件路径。
        """
        self.db_path = Path(db_path)
        # check_same_thread=False 允许多线程访问（LangGraph工具执行使用多线程）
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()  # 线程锁保护并发写入
        self._init_tables()

    def _init_tables(self):
        """初始化数据库表。"""
        cursor = self.conn.cursor()

        # 新闻表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                title TEXT NOT NULL,
                source TEXT,
                publish_time TEXT NOT NULL,
                content TEXT,
                url TEXT,
                fetch_time TEXT NOT NULL,
                UNIQUE(symbol, title, publish_time)
            )
        """)

        # 公告表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                title TEXT NOT NULL,
                type TEXT,
                publish_date TEXT NOT NULL,
                url TEXT,
                fetch_time TEXT NOT NULL,
                UNIQUE(symbol, title, publish_date)
            )
        """)

        # 财务报表表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS financial_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                report_type TEXT NOT NULL,
                report_date TEXT NOT NULL,
                data_json TEXT NOT NULL,
                fetch_time TEXT NOT NULL,
                UNIQUE(symbol, report_type, report_date)
            )
        """)

        # 分析历史表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                analyze_date TEXT NOT NULL,
                action TEXT,
                rationale TEXT,
                confidence REAL,
                full_report_path TEXT,
                agents_used TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(symbol, analyze_date)
            )
        """)

        # 数据状态表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_status (
                symbol TEXT NOT NULL,
                data_type TEXT NOT NULL,
                last_fetch_time TEXT NOT NULL,
                last_update_time TEXT,
                record_count INTEGER DEFAULT 0,
                has_new_data INTEGER DEFAULT 0,
                PRIMARY KEY(symbol, data_type)
            )
        """)

        self.conn.commit()

    def close(self):
        """关闭数据库连接。"""
        self.conn.close()

    # ==================== 新闻数据 ====================

    def save_news(self, symbol: str, news_list: List[Dict]) -> int:
        """
        保存新闻数据。

        参数：
            symbol: 股票代码。
            news_list: 新闻列表，每条新闻包含title, source, publish_time, content, url。

        返回：
            int: 新增的新闻数量。
        """
        fetch_time = datetime.now().isoformat()
        new_count = 0

        with self._lock:
            cursor = self.conn.cursor()
            for news in news_list:
                try:
                    cursor.execute("""
                        INSERT OR IGNORE INTO news
                        (symbol, title, source, publish_time, content, url, fetch_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        symbol,
                        news.get('title', ''),
                        news.get('source', ''),
                        news.get('publish_time', ''),
                        news.get('content', ''),
                        news.get('url', ''),
                        fetch_time,
                    ))
                    if cursor.rowcount > 0:
                        new_count += 1
                except Exception:
                    continue

            # 更新状态
            self._update_data_status(symbol, 'news', new_count > 0)

            self.conn.commit()
        return new_count

    def get_latest_news_time(self, symbol: str) -> Optional[str]:
        """获取数据库中该股票最新新闻的时间。"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT MAX(publish_time) as latest_time
            FROM news WHERE symbol = ?
        """, (symbol,))
        row = cursor.fetchone()
        return row['latest_time'] if row else None

    def has_new_news(self, symbol: str, check_date: str) -> bool:
        """
        检查是否有比数据库更新的新闻。

        参数：
            symbol: 股票代码。
            check_date: 检查日期。

        返回：
            bool: 是否有新新闻。
        """
        latest_time = self.get_latest_news_time(symbol)
        if latest_time is None:
            return True  # 数据库无数据，需要获取

        # 比较日期
        latest_date = latest_time.split()[0] if ' ' in latest_time else latest_time
        return check_date > latest_date

    # ==================== 公告数据 ====================

    def save_announcements(self, symbol: str, ann_list: List[Dict]) -> int:
        """保存公告数据。"""
        fetch_time = datetime.now().isoformat()
        new_count = 0

        with self._lock:
            cursor = self.conn.cursor()
            for ann in ann_list:
                try:
                    cursor.execute("""
                        INSERT OR IGNORE INTO announcements
                        (symbol, title, type, publish_date, url, fetch_time)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        symbol,
                        ann.get('title', ''),
                        ann.get('type', ''),
                        ann.get('publish_date', ''),
                        ann.get('url', ''),
                        fetch_time,
                    ))
                    if cursor.rowcount > 0:
                        new_count += 1
                except Exception:
                    continue

            self._update_data_status(symbol, 'announcements', new_count > 0)
            self.conn.commit()
        return new_count
        return new_count

    def get_latest_announcement_date(self, symbol: str) -> Optional[str]:
        """获取最新公告日期。"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT MAX(publish_date) as latest_date
            FROM announcements WHERE symbol = ?
        """, (symbol,))
        row = cursor.fetchone()
        return row['latest_date'] if row else None

    def has_new_announcements(self, symbol: str, check_date: str) -> bool:
        """检查是否有新公告。"""
        latest = self.get_latest_announcement_date(symbol)
        if latest is None:
            return True
        return check_date > latest

    # ==================== 财务报表 ====================

    def save_financial_report(
        self,
        symbol: str,
        report_type: str,
        report_date: str,
        data: Any,  # dict or list
    ) -> bool:
        """
        保存财务报表。

        参数：
            symbol: 股票代码。
            report_type: 报表类型 ('balance_sheet', 'income', 'cashflow', 'fundamentals')。
            report_date: 报告日期。
            data: 报表数据。

        返回：
            bool: 是否成功保存。
        """
        fetch_time = datetime.now().isoformat()

        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO financial_reports
                    (symbol, report_type, report_date, data_json, fetch_time)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    symbol,
                    report_type,
                    report_date,
                    json.dumps(data, ensure_ascii=False),
                    fetch_time,
                ))
                self._update_data_status(symbol, 'financials', True)
                self.conn.commit()
                return True
            except Exception:
                return False

    def get_financial_report(
        self,
        symbol: str,
        report_type: str,
        report_date: str,
    ) -> Optional[Dict]:
        """获取财务报表数据。"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT data_json FROM financial_reports
            WHERE symbol = ? AND report_type = ? AND report_date = ?
        """, (symbol, report_type, report_date))
        row = cursor.fetchone()
        if row:
            return json.loads(row['data_json'])
        return None

    def get_latest_financial_date(self, symbol: str, report_type: str) -> Optional[str]:
        """获取最新财务报告日期。"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT MAX(report_date) as latest_date
            FROM financial_reports
            WHERE symbol = ? AND report_type = ?
        """, (symbol, report_type))
        row = cursor.fetchone()
        return row['latest_date'] if row else None

    # ==================== 分析历史 ====================

    def save_analysis(
        self,
        symbol: str,
        analyze_date: str,
        action: str,
        rationale: str,
        confidence: Optional[float] = None,
        report_path: Optional[str] = None,
        agents_used: Optional[List[str]] = None,
    ):
        """保存分析结果。"""
        with self._lock:
            cursor = self.conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO analysis_history
                (symbol, analyze_date, action, rationale, confidence,
                 full_report_path, agents_used, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol,
                analyze_date,
                action,
                rationale,
                confidence,
                report_path,
                json.dumps(agents_used) if agents_used else None,
                datetime.now().isoformat(),
            ))
            self.conn.commit()

    def get_last_analysis_date(self, symbol: str) -> Optional[str]:
        """获取上次分析日期。"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT MAX(analyze_date) as last_date
            FROM analysis_history WHERE symbol = ?
        """, (symbol,))
        row = cursor.fetchone()
        return row['last_date'] if row else None

    def get_analysis(self, symbol: str, analyze_date: str) -> Optional[Dict]:
        """获取指定日期的分析结果。"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM analysis_history
            WHERE symbol = ? AND analyze_date = ?
        """, (symbol, analyze_date))
        row = cursor.fetchone()
        if row:
            return {
                'symbol': row['symbol'],
                'analyze_date': row['analyze_date'],
                'action': row['action'],
                'rationale': row['rationale'],
                'confidence': row['confidence'],
                'report_path': row['full_report_path'],
                'agents_used': json.loads(row['agents_used']) if row['agents_used'] else [],
            }
        return None

    # ==================== 数据状态 ====================

    def _update_data_status(self, symbol: str, data_type: str, has_new: bool):
        """更新数据状态。"""
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()

        cursor.execute("""
            INSERT OR REPLACE INTO data_status
            (symbol, data_type, last_fetch_time, has_new_data)
            VALUES (?, ?, ?, ?)
        """, (symbol, data_type, now, 1 if has_new else 0))

    def get_data_status(self, symbol: str, data_type: str) -> Optional[Dict]:
        """获取数据状态。"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM data_status
            WHERE symbol = ? AND data_type = ?
        """, (symbol, data_type))
        row = cursor.fetchone()
        if row:
            return {
                'last_fetch_time': row['last_fetch_time'],
                'last_update_time': row['last_update_time'],
                'record_count': row['record_count'],
                'has_new_data': row['has_new_data'],
            }
        return None

    def needs_refresh(self, symbol: str, data_type: str, max_age_days: int = 7) -> bool:
        """
        判断数据是否需要刷新。

        参数：
            symbol: 股票代码。
            data_type: 数据类型。
            max_age_days: 最大缓存天数。

        返回：
            bool: 是否需要刷新。
        """
        status = self.get_data_status(symbol, data_type)
        if status is None:
            return True

        last_fetch = datetime.fromisoformat(status['last_fetch_time'])
        age = (datetime.now() - last_fetch).days

        return age > max_age_days or status['has_new_data'] == 1

    # ==================== 综合判断 ====================

    def check_agents_needed(self, symbol: str, trade_date: str) -> Dict[str, bool]:
        """
        检查各Agent是否需要运行。

        返回字典：
        {
            'market': True,      # 行情数据每日都更新
            'news': False,       # 无新新闻，跳过
            'fundamentals': False, # 财务数据季度更新，无新数据
        }
        """
        result = {
            'market': True,  # 技术指标每日都要更新
        }

        # 检查新闻
        result['news'] = self.has_new_news(symbol, trade_date) or \
                          self.needs_refresh(symbol, 'news', max_age_days=3)

        # 检查公告
        result['announcements'] = self.has_new_announcements(symbol, trade_date) or \
                                   self.needs_refresh(symbol, 'announcements', max_age_days=7)

        # 检查财务数据（季度更新）
        latest_financial = self.get_latest_financial_date(symbol, 'balance_sheet')
        if latest_financial:
            # 财务报表通常是季度发布，检查是否超过90天
            last_date = datetime.strptime(latest_financial, "%Y%m%d")
            if (datetime.now() - last_date).days > 90:
                result['fundamentals'] = True
            else:
                result['fundamentals'] = False
        else:
            result['fundamentals'] = True

        return result

    # ==================== 统计与查询 ====================

    def get_statistics(self, symbol: Optional[str] = None) -> Dict:
        """获取数据统计。"""
        cursor = self.conn.cursor()

        stats = {}

        # 新闻统计
        if symbol:
            cursor.execute("SELECT COUNT(*) as count FROM news WHERE symbol = ?", (symbol,))
        else:
            cursor.execute("SELECT COUNT(*) as count FROM news")
        stats['news_count'] = cursor.fetchone()['count']

        # 公告统计
        if symbol:
            cursor.execute("SELECT COUNT(*) as count FROM announcements WHERE symbol = ?", (symbol,))
        else:
            cursor.execute("SELECT COUNT(*) as count FROM announcements")
        stats['announcements_count'] = cursor.fetchone()['count']

        # 分析统计
        if symbol:
            cursor.execute("SELECT COUNT(*) as count FROM analysis_history WHERE symbol = ?", (symbol,))
        else:
            cursor.execute("SELECT COUNT(*) as count FROM analysis_history")
        stats['analysis_count'] = cursor.fetchone()['count']

        return stats

    def get_stale_symbols(self, data_type: str, max_age_days: int = 7) -> List[str]:
        """获取数据过期的股票列表。"""
        cursor = self.conn.cursor()
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()

        cursor.execute("""
            SELECT symbol FROM data_status
            WHERE data_type = ? AND last_fetch_time < ?
        """, (data_type, cutoff))

        return [row['symbol'] for row in cursor.fetchall()]


# 创建全局实例（支持不同db_path）
_db_instances: Dict[str, DataCacheDB] = {}


def get_db(db_path: str = "data_cache.db") -> DataCacheDB:
    """获取数据库实例（单例模式，支持不同路径）。"""
    global _db_instances
    if db_path not in _db_instances:
        _db_instances[db_path] = DataCacheDB(db_path)
    return _db_instances[db_path]