"""组合账本：现金、持仓、费用、T+1、市值与权益曲线。

回测引擎、组合风险评估、配置优化共用这一本账，保证三处数字同源。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import rules


@dataclass
class Position:
    code: str
    qty: int = 0
    cost: float = 0.0          # 总成本（含买入费用），用于算摊薄成本
    available: int = 0         # 可卖数量（T+1：当日买入不计入）
    last_price: float = 0.0

    @property
    def avg_cost(self) -> float:
        return self.cost / self.qty if self.qty else 0.0

    @property
    def market_value(self) -> float:
        return self.qty * self.last_price

    @property
    def unrealized(self) -> float:
        return self.market_value - self.cost


@dataclass
class Trade:
    date: str
    code: str
    side: str                  # buy / sell
    price: float
    qty: int
    fees: float
    cash_delta: float          # 对现金的影响（买为负、卖为正）
    realized: float = 0.0      # 卖出时的已实现盈亏（已扣费）

    def as_row(self) -> dict:
        return {
            "date": self.date, "code": self.code, "side": self.side,
            "price": self.price, "qty": self.qty, "fees": round(self.fees, 2),
            "cash_delta": round(self.cash_delta, 2), "realized": round(self.realized, 2),
        }


class Account:
    def __init__(self, cash: float = 100_000.0, name: str = "") -> None:
        self.name = name
        self.cash0 = float(cash)
        self.cash = float(cash)
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.history: list[dict] = []
        self._day: str | None = None

    # ── 时间 ──────────────────────────────────────────────────────
    def settle(self, day: str) -> None:
        """进入新交易日：昨日买入的部分变为可卖。"""
        day = str(day)[:10]
        if self._day == day:
            return
        for pos in self.positions.values():
            pos.available = pos.qty
        self._day = day

    # ── 交易 ──────────────────────────────────────────────────────
    def buy(self, code: str, price: float, qty: int, day: str,
            limit_up: float | None = None) -> Trade:
        self.settle(day)
        reasons = rules.check_buy(code, qty, price, self.cash, limit_up)
        if reasons:
            raise rules.OrderRejected(reasons)

        amount = price * qty
        fees = rules.calc_fees(amount, "buy", str(code).zfill(6))
        pos = self.positions.setdefault(str(code).zfill(6), Position(code=str(code).zfill(6)))

        self.cash -= amount + fees.total
        pos.qty += qty
        pos.cost += amount + fees.total
        pos.last_price = price
        trade = Trade(str(day)[:10], pos.code, "buy", price, qty, fees.total,
                      -(amount + fees.total))
        self.trades.append(trade)
        return trade

    def sell(self, code: str, price: float, qty: int, day: str,
             limit_down: float | None = None) -> Trade:
        self.settle(day)
        pos = self.positions.get(str(code).zfill(6))
        qty_held = pos.qty if pos else 0
        available = pos.available if pos else 0
        reasons = rules.check_sell(code, qty, price, qty_held, available, limit_down)
        if reasons:
            raise rules.OrderRejected(reasons)

        amount = price * qty
        fees = rules.calc_fees(amount, "sell", str(code).zfill(6))
        cost_out = pos.avg_cost * qty
        realized = (amount - fees.total) - cost_out

        self.cash += amount - fees.total
        pos.qty -= qty
        pos.available -= qty
        pos.cost -= cost_out
        pos.last_price = price
        if pos.qty == 0:
            pos.cost = 0.0
            pos.available = 0

        trade = Trade(str(day)[:10], pos.code, "sell", price, qty, fees.total,
                      amount - fees.total, realized)
        self.trades.append(trade)
        return trade

    # ── 估值 ──────────────────────────────────────────────────────
    def mark(self, day: str, prices: dict[str, float] | None = None) -> float:
        """按给定价格重估，并记录当日权益。"""
        for code, px in (prices or {}).items():
            pos = self.positions.get(str(code).zfill(6))
            if pos and pos.qty:
                pos.last_price = float(px)
        equity = self.equity
        row = {
            "date": str(day)[:10],
            "cash": round(self.cash, 2),
            "market_value": round(self.market_value, 2),
            "equity": round(equity, 2),
        }
        if self.history and self.history[-1]["date"] == row["date"]:
            self.history[-1] = row
        else:
            self.history.append(row)
        return equity

    @property
    def market_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def equity(self) -> float:
        return self.cash + self.market_value

    @property
    def realized(self) -> float:
        return sum(t.realized for t in self.trades)

    @property
    def fees_paid(self) -> float:
        return sum(t.fees for t in self.trades)

    def position(self, code: str) -> Position | None:
        return self.positions.get(str(code).zfill(6))

    # ── 导出 ──────────────────────────────────────────────────────
    def trades_df(self) -> pd.DataFrame:
        return pd.DataFrame([t.as_row() for t in self.trades])

    def positions_df(self) -> pd.DataFrame:
        rows = [
            {"code": p.code, "qty": p.qty, "available": p.available,
             "avg_cost": round(p.avg_cost, 3), "last": p.last_price,
             "market_value": round(p.market_value, 2),
             "unrealized": round(p.unrealized, 2)}
            for p in self.positions.values() if p.qty
        ]
        return pd.DataFrame(rows)

    def history_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.history)

    def snapshot(self) -> dict:
        return {
            "cash": round(self.cash, 2),
            "market_value": round(self.market_value, 2),
            "equity": round(self.equity, 2),
            "realized": round(self.realized, 2),
            "fees": round(self.fees_paid, 2),
            "positions": len([p for p in self.positions.values() if p.qty]),
        }
