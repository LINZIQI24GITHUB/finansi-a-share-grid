"""内置信号：只读 OHLCV，绝不能用 shift(-n) 之类的前视。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ma_cross(df: pd.DataFrame, fast: int = 5, slow: int = 20) -> pd.Series:
    """双均线：快线上穿慢线持有，下穿离场。"""
    f = df["close"].rolling(int(fast)).mean()
    s = df["close"].rolling(int(slow)).mean()
    sig = (f > s).astype(int)
    sig[s.isna()] = 0
    return sig


def rsi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def rsi_reversion(df: pd.DataFrame, n: int = 14, low: float = 30, high: float = 70) -> pd.Series:
    r = rsi(df, n)
    out = np.zeros(len(df), dtype=int)
    holding = False
    for i in range(len(df)):
        if not holding and r.iloc[i] < low:
            holding = True
        elif holding and r.iloc[i] > high:
            holding = False
        out[i] = 1 if holding else 0
    return pd.Series(out, index=df.index)


SIGNALS = {"ma_cross": ma_cross, "rsi_reversion": rsi_reversion}


def build(name: str, df: pd.DataFrame, **params) -> pd.Series:
    if name not in SIGNALS:
        raise ValueError(f"未知信号 {name}，可选 {list(SIGNALS)}")
    return SIGNALS[name](df, **params)
