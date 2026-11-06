"""数据源协议。业务代码只认这个接口，不认 eltdx / tushare / wind。"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Protocol, Sequence, runtime_checkable

import pandas as pd


class Capability(str, Enum):
    BARS = "bars"              # 日线（含复权）
    LIMITS = "limits"          # 涨跌停价
    CALENDAR = "calendar"      # 交易日历
    STOCK_LIST = "stock_list"  # 股票清单（含 ST / 停牌标记）
    BOARDS = "boards"          # 板块成分
    DELISTED = "delisted"      # 退市股行情（防生存偏差）


class ProviderError(RuntimeError):
    """数据源不可用、字段缺失等可预期的失败。"""


class UnsupportedCapability(ProviderError):
    """当前数据源没有这项能力，调用方应降级而不是崩掉。"""


@runtime_checkable
class DataProvider(Protocol):
    name: str

    def capabilities(self) -> set[Capability]:
        ...

    def bars(self, code: str, start: str | None = None, end: str | None = None,
             adjust: str = "qfq", count: int | None = None) -> pd.DataFrame:
        """日线，列见 schema.BAR_COLUMNS；adjust ∈ {none, qfq, hfq}。

        count 给定时表示“只要最近 N 根”，用于增量补齐；实现的 provider 可忽略。
        """

    def stock_list(self, on: str | None = None) -> pd.DataFrame:
        """股票清单，列见 schema.STOCK_COLUMNS。"""

    def limits(self, codes: Sequence[str], trade_date: str) -> pd.DataFrame:
        """某交易日的真实涨跌停价，列见 schema.LIMIT_COLUMNS。"""

    def calendar(self, start: str, end: str) -> list[date]:
        """交易日列表。"""
