"""绩效指标：A 股口径，一年 252 个交易日。"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def compute(equity: pd.Series, position: pd.Series, trades: pd.DataFrame,
            fees: float, rf: float = 0.0) -> dict:
    eq = equity.astype(float)
    ret = eq.pct_change().dropna()
    n = len(eq)
    years = n / TRADING_DAYS if n else 0

    total = float(eq.iloc[-1] / eq.iloc[0] - 1) if n else 0.0
    cagr = float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1) if years > 0.2 else total
    vol = float(ret.std(ddof=1) * math.sqrt(TRADING_DAYS)) if len(ret) > 1 else 0.0
    excess = ret - rf / TRADING_DAYS
    sharpe = float(excess.mean() / ret.std(ddof=1) * math.sqrt(TRADING_DAYS)) \
        if len(ret) > 1 and ret.std(ddof=1) > 0 else 0.0
    downside = ret[ret < 0]
    sortino = float(excess.mean() / downside.std(ddof=1) * math.sqrt(TRADING_DAYS)) \
        if len(downside) > 1 and downside.std(ddof=1) > 0 else 0.0

    peak = eq.cummax()
    dd = eq / peak - 1
    max_dd = float(dd.min())
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0

    sells = trades[trades["side"] == "sell"] if not trades.empty else trades
    pnl = sells["realized"].tolist() if not sells.empty else []
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x <= 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))

    return {
        "bars": n,
        "total_return": total,
        "cagr": cagr,
        "volatility": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": max_dd,
        "calmar": calmar,
        "trades": len(pnl),
        "win_rate": len(wins) / len(pnl) if pnl else 0.0,
        "payoff": (np.mean(wins) / abs(np.mean(losses))) if wins and losses else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss else (float("inf") if gross_win else 0.0),
        "exposure": float(position.mean()) if len(position) else 0.0,
        "fees": fees,
        "final_equity": float(eq.iloc[-1]),
    }


def format_report(m: dict, title: str) -> str:
    bar = "─" * 58
    pf = "∞" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
    return "\n".join([
        bar,
        f"  {title}",
        bar,
        f"  期末权益 {m['final_equity']:>12,.0f}   总收益 {m['total_return']*100:>8.2f}%",
        f"  年化收益 {m['cagr']*100:>10.2f}%   年化波动 {m['volatility']*100:>6.2f}%",
        f"  夏普     {m['sharpe']:>10.2f}   索提诺   {m['sortino']:>6.2f}",
        f"  最大回撤 {m['max_dd']*100:>10.2f}%   卡玛     {m['calmar']:>6.2f}",
        f"  交易 {m['trades']:>4} 笔  胜率 {m['win_rate']*100:>5.1f}%  盈亏比 {m['payoff']:>4.2f}  盈利因子 {pf}",
        f"  持仓占比 {m['exposure']*100:>5.1f}%   总费用 {m['fees']:>9,.0f}",
        bar,
    ])
