from langchain_core.tools import tool
from typing import Annotated
from tradingagents.data_tools.api import run_data_tool


@tool
def get_fundamentals(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """
    获取指定股票代码的综合基本面数据。
    会先检查数据库缓存，如果已有当季数据则直接返回缓存。
    参数：
        ticker (str): 公司股票代码。
        curr_date (str): 当前交易日期，格式为 YYYY-MM-DD。
    返回：
        str: 综合基本面数据的格式化报告。
    """
    from tradingagents.data_cache import get_fetcher
    from datetime import datetime

    fetcher = get_fetcher()
    quarter_date = fetcher._get_latest_quarter_date(curr_date)
    data_str, has_new = fetcher.fetch_financials_with_cache(
        ticker, "fundamentals", quarter_date
    )
    return data_str


@tool
def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    获取指定股票代码的资产负债表数据。
    会先检查数据库缓存，如果已有当季数据则直接返回缓存。
    参数：
        ticker (str): 公司股票代码。
        freq (str): 报告频率，可选 `annual` 或 `quarterly`，默认 `quarterly`。
        curr_date (str): 当前交易日期，格式为 YYYY-MM-DD。
    返回：
        str: 资产负债表的格式化报告。
    """
    from tradingagents.data_cache import get_fetcher

    if curr_date:
        fetcher = get_fetcher()
        quarter_date = fetcher._get_latest_quarter_date(curr_date)
        data_str, has_new = fetcher.fetch_financials_with_cache(
            ticker, "balance_sheet", quarter_date
        )
        return data_str
    else:
        # 无日期参数，直接调用API
        return run_data_tool("get_balance_sheet", ticker=ticker, freq=freq, curr_date=curr_date)


@tool
def get_cashflow(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    获取指定股票代码的现金流量表数据。
    会先检查数据库缓存，如果已有当季数据则直接返回缓存。
    参数：
        ticker (str): 公司股票代码。
        freq (str): 报告频率，可选 `annual` 或 `quarterly`，默认 `quarterly`。
        curr_date (str): 当前交易日期，格式为 YYYY-MM-DD。
    返回：
        str: 现金流量表的格式化报告。
    """
    from tradingagents.data_cache import get_fetcher

    if curr_date:
        fetcher = get_fetcher()
        quarter_date = fetcher._get_latest_quarter_date(curr_date)
        data_str, has_new = fetcher.fetch_financials_with_cache(
            ticker, "cashflow", quarter_date
        )
        return data_str
    else:
        return run_data_tool("get_cashflow", ticker=ticker, freq=freq, curr_date=curr_date)


@tool
def get_income_statement(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    获取指定股票代码的利润表数据。
    会先检查数据库缓存，如果已有当季数据则直接返回缓存。
    参数：
        ticker (str): 公司股票代码。
        freq (str): 报告频率，可选 `annual` 或 `quarterly`，默认 `quarterly`。
        curr_date (str): 当前交易日期，格式为 YYYY-MM-DD。
    返回：
        str: 利润表的格式化报告。
    """
    from tradingagents.data_cache import get_fetcher

    if curr_date:
        fetcher = get_fetcher()
        quarter_date = fetcher._get_latest_quarter_date(curr_date)
        data_str, has_new = fetcher.fetch_financials_with_cache(
            ticker, "income", quarter_date
        )
        return data_str
    else:
        return run_data_tool("get_income_statement", ticker=ticker, freq=freq, curr_date=curr_date)
