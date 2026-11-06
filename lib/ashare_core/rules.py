"""A 股交易规则：费用、最小申报量、涨跌停兜底、可卖数量。

原则：**能从数据源拿到的就不自己算**。
涨跌停优先用 provider 返回的真实值（含次新、ST、退市整理期的特殊规则）；
只有拿不到时才用这里的 `limit_ratio()` 兜底。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date

COMMISSION_RATE = 0.00025
COMMISSION_MIN = 5.0
STAMP_DUTY_RATE = 0.0005   # 卖出单边
TRANSFER_FEE_RATE = 0.00001  # 双向


# ── 板块 ──────────────────────────────────────────────────────────────
def board_of(code: str) -> str:
    c = str(code).zfill(6)
    if c.startswith("688"):
        return "star"        # 科创板
    if c.startswith(("300", "301")):
        return "chinext"     # 创业板
    if c.startswith(("4", "8", "92")):
        return "bse"         # 北交所
    return "main"


def min_order_qty(code: str) -> int:
    """最小买入申报量。注意：数据源的 lot_size 是「交易单位」，不是最小申报量。

    科创板 200 股起、北交所 100 股起，其余 100 股起。
    """
    return 200 if board_of(code) == "star" else 100


def lot_step(code: str) -> int:
    """买入申报的递增单位：科创板/北交所 1 股，其余 100 股。"""
    return 1 if board_of(code) in ("star", "bse") else 100


def limit_ratio(code: str, is_st: bool = False) -> float:
    """兜底用的涨跌幅比例（拿不到真实涨跌停价时才用）。"""
    b = board_of(code)
    if b == "star" or b == "chinext":
        return 0.20
    if b == "bse":
        return 0.30
    return 0.05 if is_st else 0.10


def round_price(x: float) -> float:
    return float(f"{x + 1e-9:.2f}")


# ── 费用 ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Fees:
    commission: float
    stamp_duty: float
    transfer_fee: float

    @property
    def total(self) -> float:
        return round(self.commission + self.stamp_duty + self.transfer_fee, 2)


def is_fund(code: str) -> bool:
    """ETF / LOF：卖出不收印花税，费率跟股票不是一套。"""
    c = str(code).zfill(6)
    return c.startswith(("5", "15", "16", "18"))


def calc_fees(amount: float, side: str, code: str = "") -> Fees:
    commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
    # 印花税只对股票卖出单边征收；基金/ETF 免征
    stamp = amount * STAMP_DUTY_RATE if (side == "sell" and not is_fund(code)) else 0.0
    transfer = amount * TRANSFER_FEE_RATE
    return Fees(round(commission, 2), round(stamp, 2), round(transfer, 2))


# ── 下单校验 ──────────────────────────────────────────────────────────
class OrderRejected(ValueError):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("；".join(reasons))


def check_buy(code: str, qty: int, price: float, cash: float,
              limit_up: float | None = None) -> list[str]:
    reasons: list[str] = []
    if qty <= 0:
        return ["数量必须为正"]
    if qty < min_order_qty(code):
        reasons.append(f"{code} 最小买入 {min_order_qty(code)} 股，实际 {qty} 股")
    step = lot_step(code)
    if qty % step != 0:
        reasons.append(f"{code} 买入须为 {step} 股整数倍，实际 {qty} 股")
    if limit_up is not None and price >= limit_up - 1e-9:
        reasons.append(f"买入价 {price:.2f} 已达涨停 {limit_up:.2f}，视为无法成交")
    amount = price * qty
    need = amount + calc_fees(amount, "buy").total
    if need > cash + 1e-6:
        reasons.append(f"资金不足：需要 {need:,.2f}，可用 {cash:,.2f}")
    return reasons


def check_sell(code: str, qty: int, price: float, qty_held: int, available: int,
               limit_down: float | None = None) -> list[str]:
    reasons: list[str] = []
    if qty <= 0:
        return ["数量必须为正"]
    if qty > available:
        if qty <= qty_held:
            reasons.append(f"T+1：可卖 {available} 股，当日买入的 {qty_held - available} 股不可卖")
        else:
            reasons.append(f"持仓不足：持有 {qty_held} 股，卖出 {qty} 股")
    if limit_down is not None and price <= limit_down + 1e-9:
        reasons.append(f"卖出价 {price:.2f} 已到跌停 {limit_down:.2f}，视为无法成交")
    return reasons


# ── 交易日辅助 ────────────────────────────────────────────────────────
def is_same_day(a: str | _date, b: str | _date) -> bool:
    return str(a)[:10] == str(b)[:10]
