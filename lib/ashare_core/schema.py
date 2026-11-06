"""统一数据契约：任何 provider 返回的数据，进业务代码前都必须先过这里。"""
from __future__ import annotations

import pandas as pd

# ── 日线 ──────────────────────────────────────────────────────────────
BAR_COLUMNS = [
    "date", "code", "open", "high", "low", "close",
    "volume", "amount", "adjust", "source", "fetched_at",
]

BAR_DTYPES = {
    "code": "string",
    "open": "float64",
    "high": "float64",
    "low": "float64",
    "close": "float64",
    "volume": "float64",   # 单位：股（不是手）
    "amount": "float64",   # 单位：元
    "adjust": "string",    # none / qfq / hfq
    "source": "string",
}

# ── 股票清单 ──────────────────────────────────────────────────────────
STOCK_COLUMNS = [
    "code", "name", "exchange", "board", "lot_size",
    "is_st", "suspended", "source", "fetched_at",
]

# ── 涨跌停 ────────────────────────────────────────────────────────────
LIMIT_COLUMNS = [
    "date", "code", "pre_close", "limit_up", "limit_down",
    "limit_rule", "source", "fetched_at",
]


def normalize_bars(df: pd.DataFrame, code: str, adjust: str, source: str,
                   fetched_at: str) -> pd.DataFrame:
    """把 provider 的原始结果整理成契约格式。"""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out["code"] = str(code).zfill(6)
    out["adjust"] = adjust
    out["source"] = source
    out["fetched_at"] = fetched_at
    for col, dtype in BAR_DTYPES.items():
        if col in out.columns:
            out[col] = out[col].astype(dtype)
    out = out[BAR_COLUMNS]
    out = out.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    return out.reset_index(drop=True)


def validate_bars(df: pd.DataFrame) -> list[str]:
    """返回问题列表，空列表表示通过。"""
    problems: list[str] = []
    if df.empty:
        return ["空数据"]

    missing = [c for c in BAR_COLUMNS if c not in df.columns]
    if missing:
        return [f"缺列：{missing}"]

    if df["date"].duplicated().any():
        problems.append("日期重复")
    if not df["date"].is_monotonic_increasing:
        problems.append("日期未升序")

    for col in ("open", "high", "low", "close"):
        if (df[col] <= 0).any():
            n_bad = int((df[col] <= 0).sum())
            problems.append(
                f"{col} 有 {n_bad} 根非正数——前复权在长区间会被分红除权推到 0 以下，"
                f"改用 --adjust hfq（后复权）或缩短区间"
            )
        if df[col].isna().any():
            problems.append(f"{col} 存在空值")

    bad_high = (df["high"] < df[["open", "close"]].max(axis=1) - 1e-6).sum()
    bad_low = (df["low"] > df[["open", "close"]].min(axis=1) + 1e-6).sum()
    if bad_high:
        problems.append(f"{bad_high} 根的 high 低于 open/close")
    if bad_low:
        problems.append(f"{bad_low} 根的 low 高于 open/close")

    return problems


def slice_range(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    out = df
    if start:
        out = out[out["date"] >= start]
    if end:
        out = out[out["date"] <= end]
    return out.reset_index(drop=True)
