"""网格交易回测：档位、库存、触及成交、T+1、费用。

模型（「每格一份」）：
    锚点价 anchor 把价格切成若干档：p_i = anchor × (1 + i × step%)
    价格跌到 p_i → 买入一份（一份 = per_grid_amount 元）
    价格涨到 p_{i+1} → 卖出 p_i 上那一份
    每个档位最多持一份，卖掉的档位可以被再次触发

A 股约束（与实盘账本同源）：
    - T+1：当天买入的那份当天不能卖
    - 整手：按 100 股（科创板 200 股）取整
    - 费用：佣金最低 5 元 + 印花税卖出 0.05% + 过户费
    - 一字板（high == low）不成交
    - 跳空：买入按 min(开盘, 档位价)，卖出按 max(开盘, 档位价)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import rules


@dataclass
class Lot:
    level: int
    qty: int
    price: float
    date: str
    cost: float


@dataclass
class GridTrade:
    date: str
    side: str
    level: int
    price: float
    qty: int
    fees: float
    pnl: float = 0.0
    buy_date: str = ""


@dataclass
class GridResult:
    equity: pd.Series
    trades: list[GridTrade] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    open_lots: list[Lot] = field(default_factory=list)


def level_prices(anchor: float, step_pct: float, levels: int) -> dict[int, float]:
    step = step_pct / 100.0
    return {i: round(anchor * (1 + i * step), 2) for i in range(-levels, levels + 1)}


def run_grid(
    df: pd.DataFrame,
    code: str,
    cash: float = 200_000.0,
    step_pct: float = 2.0,
    levels: int = 10,
    per_grid_amount: float = 10_000.0,
    base_lots: int = 0,
    anchor: float | None = None,
    t1: bool = True,
) -> GridResult:
    df = df.reset_index(drop=True)
    code = str(code).zfill(6)
    lot_step = rules.lot_step(code)
    min_qty = rules.min_order_qty(code)

    anchor = float(anchor) if anchor else float(df["close"].iloc[0])
    prices = level_prices(anchor, step_pct, levels)
    low_level = -levels

    def lot_qty(price: float) -> int:
        q = int((per_grid_amount / price) // lot_step) * lot_step
        return q if q >= min_qty else 0

    lots: dict[int, Lot] = {}
    trades: list[GridTrade] = []
    equity_curve: list[float] = []
    dates = df["date"].astype(str).tolist()

    cash_left = float(cash)
    blocked = {"t1": 0, "cash": 0, "limit": 0}
    lot_blocked: set[int] = set()

    # 初始底仓：按锚点买 base_lots 档
    if base_lots > 0:
        q = lot_qty(anchor) * base_lots
        if q >= min_qty and q * anchor <= cash_left:
            amount = q * anchor
            fee = rules.calc_fees(amount, "buy").total
            if amount + fee <= cash_left:
                cash_left -= amount + fee
                lots[0] = Lot(0, q, anchor, dates[0], amount + fee)

    max_inventory = 0.0
    breach_days = 0
    prev_close = float(df["close"].iloc[0])

    for i in range(len(df)):
        row = df.iloc[i]
        day = str(row["date"])
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        froze = abs(h - l) < 1e-9  # 一字板

        # ① 卖出：从高档位往低档位扫，价格涨到 p_{i+1} 就卖掉 p_i 那份
        if not froze:
            for lv in sorted(lots.keys(), reverse=True):
                lot = lots.get(lv)
                if lot is None:
                    continue
                target = prices.get(lv + 1)
                if target is None or h < target:
                    continue
                if t1 and lot.date == day:
                    blocked["t1"] += 1
                    continue
                fill = max(o, target)
                amount = lot.qty * fill
                fee = rules.calc_fees(amount, "sell").total
                cash_left += amount - fee
                pnl = (amount - fee) - lot.cost
                trades.append(GridTrade(day, "sell", lv, fill, lot.qty, fee, pnl, lot.date))
                del lots[lv]

        # ② 买入：从低档位往上扫，价格跌到 p_i 且该档为空就买
        if not froze:
            for lv in sorted(prices.keys()):
                if lv in lots or lv < low_level:
                    continue
                target = prices[lv]
                # 只有"昨收在档位上方、今天最低价跌穿它"才算触发这一档
                if not (prev_close > target >= l):
                    continue
                q = lot_qty(target)
                if q < min_qty:
                    lot_blocked.add(lv)
                    continue
                fill = min(o, target)
                amount = q * fill
                fee = rules.calc_fees(amount, "buy").total
                if amount + fee > cash_left:
                    blocked["cash"] += 1
                    continue
                cash_left -= amount + fee
                lots[lv] = Lot(lv, q, fill, day, amount + fee)
                trades.append(GridTrade(day, "buy", lv, fill, q, fee, 0.0))

        inv_value = sum(lot.qty * c for lot in lots.values())
        max_inventory = max(max_inventory, inv_value)
        if c < prices[low_level]:
            breach_days += 1
        equity_curve.append(cash_left + inv_value)
        prev_close = c

    # 期末不做强制平仓：网格的浮亏本来就是它的一部分
    last_close = float(df["close"].iloc[-1])
    open_value = sum(lot.qty * last_close for lot in lots.values())
    open_cost = sum(lot.cost for lot in lots.values())
    final_equity = cash_left + open_value

    sells = [t for t in trades if t.side == "sell"]
    buys = [t for t in trades if t.side == "buy"]
    fees_total = sum(t.fees for t in trades)
    per_grid_profit = [t.pnl for t in sells]

    bh_return = last_close / float(df["close"].iloc[0]) - 1
    grid_return = final_equity / cash - 1
    gross_profit_per_grid = per_grid_amount * (step_pct / 100)

    stats = {
        "anchor": round(anchor, 2),
        "range": f"{prices[low_level]:.2f} ~ {prices[levels]:.2f}",
        "grid_return": grid_return,
        "buy_hold_return": bh_return,
        "excess": grid_return - bh_return,
        "buys": len(buys),
        "sells": len(sells),
        "round_trips": len(sells),
        "avg_grid_pnl": float(np.mean(per_grid_profit)) if per_grid_profit else 0.0,
        "fees_total": fees_total,
        "fee_ratio": fees_total / cash,
        "max_inventory": max_inventory,
        "max_inventory_ratio": max_inventory / cash if cash else 0.0,
        "open_lots": len(lots),
        "open_value": open_value,
        "open_cost": open_cost,
        "open_pnl": open_value - open_cost,
        "breach_days": breach_days,
        "blocked": blocked,
        "lot_blocked_levels": len(lot_blocked),
        "min_lot_cost": round(anchor * min_qty, 2),
        "final_equity": final_equity,
        "gross_per_grid": gross_profit_per_grid,
        "fee_floor_ok": gross_profit_per_grid >= 100,
    }
    return GridResult(
        equity=pd.Series(equity_curve, index=dates, name="equity"),
        trades=trades, stats=stats, open_lots=list(lots.values()),
    )
