"""策略规则：受控的白名单原语 → 可复现的 JSON 规格。

设计原则（见 DECISIONS.md）：
- 用户用自然语言说策略，Agent 翻译成**这份 JSON**，引擎只认 JSON；
- 不允许模型现写 Python（不可复现、易引入未来函数）；
- 原语白名单有限，但可以 AND/OR 组合，覆盖常见技术面策略。

规格：
{
  "entry": [ {"ind": "ma_cross", "fast": 5, "slow": 20}, ... ],   # 全部满足才买（AND）
  "exit":  [ {"ind": "rsi", "n": 14, "gt": 70}, ... ],             # 任意满足就卖（OR）
  "stop_loss": 8.0,          # 可选，百分比；按日内最低价触发
  "take_profit": 20.0        # 可选，百分比；按日内最高价触发
}
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

WHITELIST = {"ma_cross", "price_above_ma", "rsi", "bollinger", "breakout", "vol_ma"}

REQUIRED = {
    "ma_cross": {"fast": int, "slow": int},
    "price_above_ma": {"n": int},
    "rsi": {"n": int},
    "bollinger": {"n": int},
    "breakout": {"n": int},
    "vol_ma": {"fast": int, "slow": int},
}


# ── 校验 ──────────────────────────────────────────────────────────────
def validate(spec: dict) -> list[str]:
    problems: list[str] = []
    if not isinstance(spec, dict):
        return ["规则必须是一个 JSON 对象"]
    entry = spec.get("entry")
    if not entry:
        problems.append("缺少 entry（入场条件）")
    for key in ("entry", "exit"):
        conds = spec.get(key) or []
        if not isinstance(conds, list):
            problems.append(f"{key} 必须是数组")
            continue
        for i, cond in enumerate(conds):
            if not isinstance(cond, dict):
                problems.append(f"{key}[{i}] 必须是对象")
                continue
            ind = cond.get("ind")
            if ind not in WHITELIST:
                problems.append(f"{key}[{i}] 不支持的指标：{ind}（可用：{', '.join(sorted(WHITELIST))}）")
                continue
            for field, typ in REQUIRED[ind].items():
                if not isinstance(cond.get(field), typ):
                    problems.append(f"{key}[{i}] {ind} 缺少参数 {field}（{typ.__name__}）")
            if ind == "rsi" and not any(k in cond for k in ("lt", "gt", "cross_above", "cross_below")):
                problems.append(f"{key}[{i}] rsi 需要 lt / gt 之一")
    for key in ("stop_loss", "take_profit"):
        v = spec.get(key)
        if v is not None and not (isinstance(v, (int, float)) and 0 < v < 100):
            problems.append(f"{key} 必须是 0–100 之间的百分比")
    return problems


# ── 条件求值 ──────────────────────────────────────────────────────────
def _ma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(int(n)).mean()


def _cond(df: pd.DataFrame, cond: dict) -> pd.Series:
    ind = cond["ind"]
    close = df["close"]

    if ind == "ma_cross":
        f, s = _ma(close, cond["fast"]), _ma(close, cond["slow"])
        return (f > s) & s.notna()

    if ind == "price_above_ma":
        ma = _ma(close, cond["n"])
        return (close > ma) & ma.notna()

    if ind == "vol_ma":
        # 成交量均线：默认 fast 在 slow 上方；below=true 表示反之（放量/缩量切换）
        vol = df["volume"]
        f, s = _ma(vol, cond["fast"]), _ma(vol, cond["slow"])
        return ((f < s) if cond.get("below") else (f > s)) & s.notna()

    if ind == "rsi":
        n = int(cond.get("n", 14))
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
        r = (100 - 100 / (1 + gain / loss.replace(0, np.nan))).fillna(50)
        if "lt" in cond:
            return r < cond["lt"]
        if "gt" in cond:
            return r > cond["gt"]
        if "cross_above" in cond:
            return (r > cond["cross_above"]) & (r.shift(1) <= cond["cross_above"])
        return (r < cond["cross_below"]) & (r.shift(1) >= cond["cross_below"])

    if ind == "bollinger":
        n, k = int(cond["n"]), float(cond.get("k", 2.0))
        mid = _ma(close, n)
        sd = close.rolling(n).std(ddof=0)
        lower = mid - k * sd
        if cond.get("side", "lower") == "upper":
            return (close > mid + k * sd) & lower.notna()
        return (close < lower) & lower.notna()

    # breakout：突破前 n 日最高收盘（用 shift 避免用到当天）
    n = int(cond["n"])
    hi = close.rolling(n).max().shift(1)
    return (close > hi) & hi.notna()


def _combine(df: pd.DataFrame, conds: list[dict], how: str) -> pd.Series:
    if not conds:
        return pd.Series(False, index=df.index)
    parts = [_cond(df, c) for c in conds]
    out = parts[0]
    for p in parts[1:]:
        out = (out & p) if how == "and" else (out | p)
    return out.fillna(False)


# ── 生成仓位序列 ──────────────────────────────────────────────────────
def build_position(df: pd.DataFrame, spec: dict) -> pd.Series:
    """入场条件全部满足则持有；出场条件任一满足则空仓。"""
    entry = _combine(df, spec.get("entry") or [], "and")
    exit_ = _combine(df, spec.get("exit") or [], "or")
    pos = np.zeros(len(df), dtype=int)
    holding = False
    for i in range(len(df)):
        if not holding and bool(entry.iloc[i]):
            holding = True
        elif holding and bool(exit_.iloc[i]):
            holding = False
        pos[i] = 1 if holding else 0
    return pd.Series(pos, index=df.index)


# ── 人话描述 ──────────────────────────────────────────────────────────
_LABEL = {
    "ma_cross": lambda c: f"均线 {c['fast']}/{c['slow']} 金叉",
    "price_above_ma": lambda c: f"收盘站上 {c['n']} 日均线",
    "rsi": lambda c: (f"RSI({c.get('n', 14)}) < {c['lt']}" if "lt" in c
                      else f"RSI({c.get('n', 14)}) > {c['gt']}"),
    "bollinger": lambda c: f"跌破布林下轨({c['n']},{c.get('k', 2.0)})",
    "breakout": lambda c: f"突破 {c['n']} 日新高",
    "vol_ma": lambda c: (f"成交量 MA{c['fast']} {'<' if c.get('below') else '>'} MA{c['slow']}"),
}


def describe(spec: dict) -> str:
    entry = " AND ".join(_LABEL.get(c["ind"], lambda x: c["ind"])(c) for c in spec.get("entry", []))
    exit_ = " OR ".join(_LABEL.get(c["ind"], lambda x: c["ind"])(c) for c in spec.get("exit", [])) or "无"
    bits = [f"入场 {entry}", f"出场 {exit_}"]
    if spec.get("stop_loss"):
        bits.append(f"止损 {spec['stop_loss']}%")
    if spec.get("take_profit"):
        bits.append(f"止盈 {spec['take_profit']}%")
    return "；".join(bits)


def load(text: str) -> dict:
    """接受 JSON 字符串或文件路径。"""
    from pathlib import Path

    p = Path(text)
    raw = p.read_text(encoding="utf-8") if p.exists() else text
    spec = json.loads(raw)
    problems = validate(spec)
    if problems:
        raise ValueError("规则不合法：" + "；".join(problems))
    return spec
