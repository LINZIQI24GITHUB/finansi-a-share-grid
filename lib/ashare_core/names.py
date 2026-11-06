"""股票简称查表：本地缓存优先，缺了才问数据源。

图表标题、报告表头都需要「宁德时代 300750」这种写法；
把名字缓存到 data/names.json，第二次之后就不用再查。
"""
from __future__ import annotations

import json
from pathlib import Path


def _path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "names.json"


def remember_name(code: str, name: str, data_dir: str | Path) -> None:
    if not name:
        return
    try:
        path = _path(data_dir)
        names = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        names[str(code).zfill(6)] = name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 - 名字缓存只是锦上添花
        pass


def lookup_name(code: str, data_dir: str | Path) -> str:
    """查不到就返回空串，调用方自己决定是否只显示代码。"""
    code = str(code).zfill(6)
    try:
        path = _path(data_dir)
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8")).get(code, "")
            if cached:
                return str(cached)
    except Exception:  # noqa: BLE001
        pass
    try:
        from .providers.eltdx_provider import EltdxProvider

        with EltdxProvider() as p:
            lst = p.stock_list()
        hit = lst[lst["code"] == code]
        if len(hit):
            name = str(hit.iloc[0]["name"])
            remember_name(code, name, data_dir)
            return name
    except Exception:  # noqa: BLE001
        pass
    return ""
