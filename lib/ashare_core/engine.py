"""日频回测引擎：信号次日开盘成交，成交前过一遍账本的真实规则。

设计要点：
- 信号只用当日及之前的数据（由调用方保证），引擎在第 i+1 根开盘执行；
- 涨跌停默认按板块比例兜底计算，需要精确值时可注入 limit_fn；
- 所有成交都走 Account，费用 / T+1 / 最小申报量与实盘完全同一套代码。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import rules
from .account import Account


@dataclass
class BacktestResult:
    account: Account
    equity: pd.Series
    position: pd.Series
    blocked: dict = field(default_factory=dict)

    def summary(self) -> dict:
        return {**self.account.snapshot(), "blocked": self.blocked}


def _limit_prices(prev_close: float, code: str, is_st: bool) -> tuple[float, float]:
    """返回 (涨停价, 跌停价)。"""
    pct = rules.limit_ratio(code, is_st)
    return (rules.round_price(prev_close * (1 + pct)),
            rules.round_price(prev_close * (1 - pct)))


def run(
    df: pd.DataFrame,
    signal: pd.Series,
    code: str,
    cash: float = 100_000.0,
    is_st: bool = False,
    slippage: float = 0.0,
    stop_loss: float | None = None,
    take_profit: float | None = None,
) -> BacktestResult:
    """stop_loss / take_profit 为百分比（如 8 表示 8%），按**日内**最高/最低价触发。

    触发价逻辑：
    - 止损：low ≤ 止损价 → 以 min(开盘价, 止损价) 成交（跳空低开按开盘价，更差但真实）
    - 止盈：high ≥ 止盈价 → 以 max(开盘价, 止盈价) 成交
    - 跌停当天的止损卖不出去，计入 blocked
    - 被止损/止盈打出来后，必须等信号重新归零才允许再进场（避免同一信号反复接飞刀）
    """
    df = df.reset_index(drop=True)
    sig = pd.Series(signal).reset_index(drop=True).fillna(0).astype(int).clip(0, 1)
    code = str(code).zfill(6)
    min_qty = rules.min_order_qty(code)
    step = rules.lot_step(code)

    acct = Account(cash)
    blocked = {"limit_up": 0, "limit_down": 0, "cash": 0, "t1": 0,
               "stop": 0, "take_profit": 0}

    equity, positions = [], []
    prev_close: float | None = None
    entry_px: float | None = None
    entry_i: int | None = None
    reentry_block = False

    for i in range(len(df)):
        row = df.iloc[i]
        day = row["date"]
        o, c = float(row["open"]), float(row["close"])
        hi, lo = float(row["high"]), float(row["low"])
        acct.settle(day)

        if i > 0 and prev_close is not None:
            pos = acct.position(code)
            held = pos.qty if pos else 0
            up, down = _limit_prices(prev_close, code, is_st)
            sold_today = False

            # ① 先看止损止盈（日内触发）
            if held and entry_px and entry_i is not None and i > entry_i:
                hit_px = None
                reason = None
                if stop_loss:
                    stop_px = entry_px * (1 - stop_loss / 100)
                    if lo <= stop_px:
                        hit_px, reason = min(o, stop_px), "stop"
                if hit_px is None and take_profit:
                    tp_px = entry_px * (1 + take_profit / 100)
                    if hi >= tp_px:
                        hit_px, reason = max(o, tp_px), "take_profit"
                if hit_px is not None:
                    try:
                        acct.sell(code, hit_px, held, day, limit_down=down)
                        blocked[reason] += 1
                        sold_today = True
                        reentry_block = True
                        entry_px, entry_i = None, None
                    except rules.OrderRejected as e:
                        blocked["limit_down" if any("跌停" in r for r in e.reasons) else "t1"] += 1

            # ② 再执行昨日收盘的信号
            if not sold_today:
                target = int(sig.iloc[i - 1])
                if target == 0:
                    reentry_block = False
                if target == 1 and held == 0 and not reentry_block:
                    px = o * (1 + slippage)
                    budget = acct.cash
                    lot = int((budget / (px * (1 + rules.COMMISSION_RATE + rules.TRANSFER_FEE_RATE))) // step) * step
                    if lot < min_qty:
                        blocked["cash"] += 1
                    else:
                        try:
                            acct.buy(code, px, lot, day, limit_up=up)
                            entry_px, entry_i = px, i
                        except rules.OrderRejected as e:
                            blocked["limit_up" if any("涨停" in r for r in e.reasons) else "cash"] += 1
                elif target == 0 and held > 0:
                    px = o * (1 - slippage)
                    try:
                        acct.sell(code, px, held, day, limit_down=down)
                        entry_px, entry_i = None, None
                    except rules.OrderRejected as e:
                        blocked["limit_down" if any("跌停" in r for r in e.reasons) else "t1"] += 1

        acct.mark(day, {code: c})
        equity.append(acct.equity)
        positions.append(1 if (acct.position(code) and acct.position(code).qty) else 0)
        prev_close = c

    return BacktestResult(
        account=acct,
        equity=pd.Series(equity, index=df["date"].tolist(), name="equity"),
        position=pd.Series(positions, index=df["date"].tolist(), name="position"),
        blocked=blocked,
    )
