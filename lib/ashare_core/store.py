"""本地 parquet 缓存：先读盘、再补网，增量合并。

目录结构：
    data/bars/{code}.parquet     # 每只股票一个文件（含全部历史）
    data/manifest.json           # 每只票的复权口径、最后日期、行数
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import schema
from .providers.base import DataProvider

RECENT_BARS = 260  # 增量时向前多取一年，覆盖分红调整引起的整段变化


class BarsCache:
    def __init__(self, provider: DataProvider, root: str | Path) -> None:
        self.provider = provider
        self.root = Path(root)
        self.bars_dir = self.root / "bars"
        self.bars_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / "manifest.json"
        self._manifest = self._read_manifest()

    # ── manifest ─────────────────────────────────────────────────
    def _read_manifest(self) -> dict:
        if self.manifest_path.exists():
            try:
                return json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def _write_manifest(self) -> None:
        self.manifest_path.write_text(
            json.dumps(self._manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 读写 ─────────────────────────────────────────────────────
    def _path(self, code: str, adjust: str = "qfq") -> Path:
        return self.bars_dir / f"{str(code).zfill(6)}.{adjust}.parquet"

    def load(self, code: str, adjust: str = "qfq") -> pd.DataFrame | None:
        path = self._path(code, adjust)
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def save(self, code: str, df: pd.DataFrame) -> None:
        adjust = str(df["adjust"].iloc[-1])
        df.to_parquet(self._path(code, adjust), index=False, compression="zstd")
        self._manifest[f"{str(code).zfill(6)}:{adjust}"] = {
            "adjust": adjust,
            "last_date": str(df["date"].iloc[-1]),
            "rows": int(len(df)),
            "source": str(df["source"].iloc[-1]),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._write_manifest()

    # ── 取数主入口 ───────────────────────────────────────────────
    def get(self, code: str, start: str | None = None, end: str | None = None,
            adjust: str = "qfq", refresh: bool = False) -> pd.DataFrame:
        cached = None if refresh else self.load(code, adjust)

        if cached is not None and not cached.empty:
            same_adjust = str(cached["adjust"].iloc[-1]) == adjust
            covered = (start is None or cached["date"].min() <= start) and \
                      (end is None or cached["date"].max() >= end)
            if same_adjust and covered:
                return schema.slice_range(cached, start, end)

            if same_adjust:
                # 增量：只补最近一段，再与缓存合并
                recent = self.provider.bars(code, adjust=adjust, count=RECENT_BARS)
                merged = pd.concat([cached, recent], ignore_index=True)
                merged = merged.drop_duplicates(subset=["date"], keep="last") \
                               .sort_values("date").reset_index(drop=True)
                self.save(code, merged)
                return schema.slice_range(merged, start, end)

        # 全量
        fresh = self.provider.bars(code, adjust=adjust)
        self.save(code, fresh)
        return schema.slice_range(fresh, start, end)

    # ── 组合视图 ─────────────────────────────────────────────────
    def panel(self, codes: list[str], start: str, end: str, adjust: str = "qfq",
              field: str = "close") -> pd.DataFrame:
        """date × code 的矩阵，供组合分析使用。"""
        series = []
        for code in codes:
            df = self.get(code, start, end, adjust)
            s = df.set_index("date")[field].rename(str(code).zfill(6))
            series.append(s)
        return pd.concat(series, axis=1).sort_index() if series else pd.DataFrame()
