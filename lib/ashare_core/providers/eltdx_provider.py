"""eltdx 适配层。

⚠️ 这是整个包里 **唯一** 允许 import eltdx 的文件。
换数据源时，只需要再写一个 provider 并改 pack.json，业务代码不动。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Sequence

import pandas as pd

from .. import schema
from .base import Capability, DataProvider, ProviderError

_ADJUST = {"none": None, "qfq": "qfq", "hfq": "hfq"}
_BOARD_MAP = {
    "sse_main_board": "主板", "sse_star_market": "科创板",
    "szse_main_board": "主板", "szse_chinext": "创业板",
    "bse": "北交所", "bse_main": "北交所",
}


def full_code(code: str) -> str:
    """600519 -> sh600519；510300 -> sh510300（ETF 走沪市）；已是带前缀的原样返回。"""
    c = str(code).strip().lower()
    if c.startswith(("sh", "sz", "bj")):
        return c
    c = c.zfill(6)
    if c.startswith("92"):              # 北交所 920 新号段
        return f"bj{c}"
    if c.startswith(("5", "6", "9")):   # 沪市股票 + 沪市 ETF/基金
        return f"sh{c}"
    if c.startswith(("4", "8")):
        return f"bj{c}"
    return f"sz{c}"


def bare_code(code: str) -> str:
    c = str(code).strip().lower()
    return c[2:] if c.startswith(("sh", "sz", "bj")) else c.zfill(6)


class EltdxProvider(DataProvider):
    name = "eltdx"

    def __init__(self, timeout: float = 8.0) -> None:
        try:
            from eltdx import TdxClient
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("未安装 eltdx，请先 pip install eltdx") from exc
        self._client = TdxClient(timeout=timeout)
        self._connected = False

    # ── 生命周期 ──────────────────────────────────────────────────
    def _c(self):
        if not self._connected:
            self._client.connect()
            self._connected = True
        return self._client

    def close(self) -> None:
        if self._connected:
            self._client.close()
            self._connected = False

    def __enter__(self):
        self._c()
        return self

    def __exit__(self, *exc):
        self.close()

    # ── 能力 ──────────────────────────────────────────────────────
    def capabilities(self) -> set[Capability]:
        return {Capability.BARS, Capability.LIMITS, Capability.CALENDAR,
                Capability.STOCK_LIST, Capability.DELISTED}

    # ── 行情 ──────────────────────────────────────────────────────
    def bars(self, code: str, start: str | None = None, end: str | None = None,
             adjust: str = "qfq", count: int | None = None) -> pd.DataFrame:
        if adjust not in _ADJUST:
            raise ProviderError(f"不支持的复权口径：{adjust}")
        fc = full_code(code)
        try:
            series = self._c().bars.get(
                fc, period="day",
                count=count or 8000,
                adjust=_ADJUST[adjust],
                all_pages=count is None,
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"取 {fc} 日线失败：{type(exc).__name__}: {exc}") from exc

        rows = [
            {
                "date": b.time.strftime("%Y-%m-%d"),
                "open": float(b.open), "high": float(b.high),
                "low": float(b.low), "close": float(b.close),
                "volume": float(b.volume_lots) * 100.0,   # 手 -> 股
                "amount": float(b.amount),
            }
            for b in series.bars
        ]
        df = pd.DataFrame(rows)
        if df.empty:
            raise ProviderError(f"{fc} 没有返回数据")
        df = schema.normalize_bars(df, bare_code(code), adjust, self.name,
                                   datetime.now().isoformat(timespec="seconds"))
        return schema.slice_range(df, start, end)

    # ── 清单 ──────────────────────────────────────────────────────
    def stock_list(self, on: str | None = None) -> pd.DataFrame:
        try:
            raw = self._c().helpers.latest_stock_list()
            suspended = {x.code for x in self._c().helpers.latest_suspended()}
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"取股票清单失败：{type(exc).__name__}: {exc}") from exc

        rows = []
        for s in raw:
            name = s.name or ""
            rows.append({
                "code": str(s.code).zfill(6),
                "name": name,
                "exchange": s.exchange,
                "board": _BOARD_MAP.get(getattr(s, "board", ""), getattr(s, "board", "") or ""),
                "lot_size": int(getattr(s, "multiple", 100) or 100),
                "is_st": name.startswith(("ST", "*ST", "S*ST", "SST")),
                "suspended": str(s.code).zfill(6) in suspended,
                "source": self.name,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            })
        return pd.DataFrame(rows, columns=schema.STOCK_COLUMNS)

    # ── 涨跌停 ────────────────────────────────────────────────────
    def limits(self, codes: Sequence[str], trade_date: str) -> pd.DataFrame:
        try:
            table = self._c().helpers.daily_price_limits(
                [full_code(c) for c in codes], trade_date=trade_date)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"取涨跌停失败：{type(exc).__name__}: {exc}") from exc

        rows = [
            {
                "date": str(r.trade_date),
                "code": bare_code(r.full_code),
                "pre_close": float(r.pre_close),
                "limit_up": float(r.limit_up_price),
                "limit_down": float(r.limit_down_price),
                "limit_rule": r.limit_rule,
                "source": self.name,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            }
            for r in getattr(table, "rows", table)
        ]
        return pd.DataFrame(rows, columns=schema.LIMIT_COLUMNS)

    # ── 日历 ──────────────────────────────────────────────────────
    def calendar(self, start: str, end: str) -> list[date]:
        days = self._c().workdays.range(start, end)
        return [d if isinstance(d, date) else datetime.strptime(str(d), "%Y-%m-%d").date()
                for d in days]
