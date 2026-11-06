#!/usr/bin/env python3
"""A 股网格回测：档位库存模型 + T+1 + 参数扫描。

    python scripts/run.py run  --code 300750 --start 2024-01-01 --end 2025-12-31 \
        --step 2 --levels 10 --amount 10000 --cash 200000
    python scripts/run.py sweep --code 300750 --start 2024-01-01 --end 2025-12-31
    python scripts/run.py demo            # 离线自检

口径与 a-share-backtest 一致：后复权收益 + 按窗口首日真实价缩放，
这样档位价是真实价格，收益口径又不受分红除权污染。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
for candidate in (os.getenv("ASHARE_LIB"),
                  SKILL_DIR.parents[1] / "lib" if len(SKILL_DIR.parents) > 1 else None,
                  SKILL_DIR / "lib"):
    if candidate and Path(candidate).is_dir() and (Path(candidate) / "ashare_core").is_dir():
        sys.path.insert(0, str(candidate))
        break

from ashare_core import grid, names  # noqa: E402
from ashare_core.providers.eltdx_provider import EltdxProvider  # noqa: E402
from ashare_core.store import BarsCache  # noqa: E402


def _default_data_dir() -> Path:
    env = os.getenv("ASHARE_DATA")
    if env:
        return Path(env)
    pack_data = SKILL_DIR.parents[1] / "data" if len(SKILL_DIR.parents) > 1 else None
    if pack_data and (pack_data.exists() or (SKILL_DIR.parents[1] / "lib").exists()):
        return pack_data
    return Path.home() / ".ashare" / "data"


DATA = _default_data_dir()


def resolve_code(raw: str, provider) -> str:
    s = str(raw).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits and len(digits) <= 6:
        return digits.zfill(6)
    lst = provider.stock_list()
    hit = lst[lst["name"] == s]
    if hit.empty:
        hit = lst[lst["name"].str.contains(s, na=False)]
    if hit.empty:
        raise SystemExit(f"✗ 找不到名称含「{s}」的股票，请改用 6 位代码")
    if len(hit) > 1:
        names = "、".join(f"{r.code} {r.name}" for r in hit.head(6).itertuples())
        raise SystemExit(f"✗ 「{s}」匹配到多只：{names}，请指定代码")
    return str(hit.iloc[0]["code"])


def load_scaled(cache: BarsCache, code: str, start: str, end: str):
    hfq = cache.get(code, start, end, "hfq")
    raw = cache.get(code, start, end, "none")
    if hfq.empty or raw.empty:
        raise SystemExit(f"✗ {code} 取数失败")
    first = str(hfq["date"].iloc[0])
    raw0 = raw[raw["date"] == first]["close"]
    if raw0.empty:
        raise SystemExit(f"✗ {code} 在 {first} 没有不复权价格，无法锚定")
    scale = float(raw0.iloc[0]) / float(hfq["close"].iloc[0])
    df = hfq.copy()
    for col in ("open", "high", "low", "close"):
        df[col] = (df[col] * scale).round(2)
    return df, scale


def fetch(code: str, start: str, end: str):
    with EltdxProvider() as p:
        cache = BarsCache(p, DATA)
        resolved = resolve_code(code, p)
        df, scale = load_scaled(cache, resolved, start, end)
    return resolved, df, scale


def _grid_metrics(res, stats: dict, n_bars: int) -> dict:
    """把网格结果映射成 chart.kpi_items 认识的指标字段（数字同源，不在画图时重算）。"""
    eq = res.equity.astype(float)
    ret = eq.pct_change().dropna()
    std = float(ret.std(ddof=1)) if len(ret) > 1 else 0.0
    vol = std * math.sqrt(252)
    sharpe = float(ret.mean() / std * math.sqrt(252)) if std else 0.0
    max_dd = float((eq / eq.cummax() - 1).min())
    years = n_bars / 252
    cagr = (1 + stats["grid_return"]) ** (1 / years) - 1 if years > 0.2 else stats["grid_return"]

    sells = [t.pnl for t in res.trades if t.side == "sell"]
    wins = [x for x in sells if x > 0]
    losses = [x for x in sells if x <= 0]
    payoff = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else 0.0
    return {
        "total_return": stats["grid_return"],
        "cagr": cagr,
        "max_dd": max_dd,
        "volatility": vol,
        "sharpe": sharpe,
        "trades": len(sells),
        "win_rate": len(wins) / len(sells) if sells else 0.0,
        "payoff": payoff,
    }


def _plot(path: Path, res, df, code: str, stats: dict, step: float, levels: int, amount: float,
          name: str = "") -> None:
    """品牌化权益图：网格权益 vs 买入持有基准。matplotlib 缺失时静默跳过。"""
    try:
        import pandas as pd
        from ashare_core import chart
    except Exception:  # noqa: BLE001
        return
    met = _grid_metrics(res, stats, len(df))
    bench = pd.Series(res.equity.iloc[0] * df["close"].values / float(df["close"].iloc[0]),
                      index=res.equity.index)
    out = chart.render(
        path, res.equity, met,
        title=f"{name} {code} 网格回测".strip(),
        desc=f"格宽 {step:g}% · {levels} 档 · 每格 {amount:,.0f} 元",
        period=f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]} · 后复权",
        benchmark=bench,
    )
    if out:
        print(f"  权益图 → {out}")


def cmd_run(args) -> int:
    code, df, scale = fetch(args.code, args.start, args.end)
    res = grid.run_grid(df, code, cash=args.cash, step_pct=args.step,
                        levels=args.levels, per_grid_amount=args.amount,
                        base_lots=args.base_lots, anchor=args.anchor)
    s = res.stats
    if args.json:
        print(json.dumps({"code": code, "stats": s, "scale": scale},
                         ensure_ascii=False, indent=2, default=str))
        return 0

    bar = "─" * 60
    print(bar)
    print(f"  {code} · 网格 step={args.step}% levels={args.levels} 每格{args.amount:,.0f}元")
    print(bar)
    print(f"  网格收益 {s['grid_return']*100:>8.2f}%     买入持有 {s['buy_hold_return']*100:>8.2f}%"
          f"     超额 {s['excess']*100:>+7.2f}%")
    print(f"  区间 {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}（{len(df)} 根）"
          f"  锚点 {s['anchor']:.2f}  网格 {s['range']}")
    print(f"  成交 {s['sells']:>4} 次卖出 / {s['buys']:>4} 次买入    "
          f"每格平均利润 {s['avg_grid_pnl']:>8,.2f} 元")
    print(f"  费用 {s['fees_total']:>9,.0f} 元（占本金 {s['fee_ratio']*100:.2f}%）   "
          f"单格毛利 {s['gross_per_grid']:,.0f} 元")
    print(f"  最大库存 {s['max_inventory']:>10,.0f} 元（{s['max_inventory_ratio']*100:.1f}% 本金）"
          f"   期末持仓 {s['open_lots']} 格 / {s['open_value']:,.0f} 元")
    print(f"  未平仓浮亏 {s['open_pnl']:>+10,.0f} 元   破网天数 {s['breach_days']}")
    print(f"  期末权益 {s['final_equity']:>10,.0f} 元   口径 后复权 × {scale:.4f}")
    b = s["blocked"]
    print(f"  被挡：T+1 {b['t1']} 次，资金不足 {b['cash']} 次，买不起一手的档位 {s['lot_blocked_levels']} 个")

    if args.amount < s["min_lot_cost"]:
        print(f"\n  ⚠ 每格 {args.amount:,.0f} 元买不起一手（锚点一手约 {s['min_lot_cost']:,.0f} 元）——"
              f"把 --amount 调到 {s['min_lot_cost']*1.1:,.0f} 以上，否则大量档位根本不会成交")
    if not s["fee_floor_ok"]:
        print(f"\n  ⚠ 单格毛利只有 {s['gross_per_grid']:,.0f} 元，低于 100 元警戒线——"
              f"最低佣金会吃掉大部分利润，建议加大每格金额或放宽格宽")
    if s["breach_days"] > 0:
        print(f"  ⚠ 有 {s['breach_days']} 天跌破网格下沿，超出部分不再自动买入（破网）")

    print(bar)

    if not args.no_plot:
        out_png = Path(args.plot) if args.plot else (
            SKILL_DIR / "out" / f"grid_{code}_{args.step:g}_{args.levels}.png")
        out_png.parent.mkdir(parents=True, exist_ok=True)
        stock_name = names.lookup_name(code, DATA)
        _plot(out_png, res, df, code, s, args.step, args.levels, args.amount, stock_name)

    if res.trades:
        print("\n最近 6 笔成交")
        for t in res.trades[-6:]:
            flag = "卖" if t.side == "sell" else "买"
            print(f"  {t.date}  {flag}  L{t.level:+d}  {t.qty:>6}股 @ {t.price:>8.2f}"
                  f"  费用 {t.fees:>6.2f}" + (f"  盈亏 {t.pnl:>+9,.0f}" if t.side == "sell" else ""))
    return 0


def cmd_sweep(args) -> int:
    code, df, _ = fetch(args.code, args.start, args.end)
    print(f"{code}  {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}  {len(df)} 根")
    print(f"本金 {args.cash:,.0f} 元，每格 {args.amount:,.0f} 元，扫描 格宽 × 档数\n")
    header = f"{'格宽':>5} {'档数':>5} {'网格收益':>9} {'买入持有':>9} {'超额':>8} {'卖出次数':>7} {'费用':>8} {'破网天':>5}"
    print(header)
    print("-" * len(header))
    rows = []
    for step in (1.0, 2.0, 3.0, 5.0):
        for levels in (5, 10, 20):
            r = grid.run_grid(df, code, cash=args.cash, step_pct=step, levels=levels,
                              per_grid_amount=args.amount, base_lots=args.base_lots)
            s = r.stats
            rows.append((step, levels, s))
            print(f"{step:>4.0f}% {levels:>5} {s['grid_return']*100:>8.2f}% "
                  f"{s['buy_hold_return']*100:>8.2f}% {s['excess']*100:>+7.2f}% "
                  f"{s['sells']:>9} {s['fees_total']:>8,.0f} {s['breach_days']:>7}")
    best = max(rows, key=lambda x: x[2]["grid_return"])
    print(f"\n收益最高：格宽 {best[0]:.0f}%、{best[1]} 档 → {best[2]['grid_return']*100:.2f}%"
          f"（买入持有 {best[2]['buy_hold_return']*100:.2f}%）")
    print("注：同一段数据挑最优参数必然过拟合，这里的价值是看趋势，不是选参数。")
    return 0


def cmd_demo(args) -> int:
    code, start, end = "300750", "2024-01-01", "2025-12-31"
    _, df, _ = fetch(code, start, end)
    res = grid.run_grid(df, code, cash=200_000, step_pct=2.0, levels=10,
                        per_grid_amount=20_000, base_lots=0)
    s = res.stats

    bad_t1 = [t for t in res.trades if t.side == "sell" and t.buy_date >= t.date]

    checks = [
        ("成交次数 > 0", s["sells"] > 0, f"{s['sells']} 次卖出"),
        ("每格平均利润 > 0", s["avg_grid_pnl"] > 0, f"{s['avg_grid_pnl']:.2f} 元"),
        ("期末权益 > 0", s["final_equity"] > 0, f"{s['final_equity']:,.0f}"),
        ("每笔卖出都满足 T+1", not bad_t1, f"{len(bad_t1)} 笔违反"),
        ("单格毛利 ≥ 100", s["fee_floor_ok"], f"{s['gross_per_grid']:,.0f} 元"),
    ]
    print(f"离线自检：{code} 网格 step=2% levels=10 每格2万")
    passed = 0
    for name, ok, detail in checks:
        passed += ok
        print(f"  {'✓' if ok else '✗'} {name}：{detail}")
    print(f"\n  网格 {s['grid_return']*100:.2f}%  vs  买入持有 {s['buy_hold_return']*100:.2f}%"
          f"  卖出 {s['sells']} 次  费用 {s['fees_total']:,.0f} 元")
    total = len(checks)
    print(f"\n{'✓ 通过' if passed == total else '✗ 未通过'}（{passed}/{total}）")
    return 0 if passed == total else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="A 股网格回测")
    ap.add_argument("--data-dir", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, func in (("run", cmd_run), ("sweep", cmd_sweep)):
        p = sub.add_parser(name)
        p.add_argument("--code", required=True)
        p.add_argument("--start", required=True)
        p.add_argument("--end", required=True)
        p.add_argument("--cash", type=float, default=200_000.0)
        p.add_argument("--amount", type=float, default=10_000.0)
        p.add_argument("--base-lots", type=int, default=0)
        if name == "run":
            p.add_argument("--step", type=float, default=2.0)
            p.add_argument("--levels", type=int, default=10)
            p.add_argument("--anchor", type=float, default=None)
            p.add_argument("--json", action="store_true")
            p.add_argument("--plot", default=None, help="权益图输出路径")
            p.add_argument("--no-plot", action="store_true", help="不出图（调试用）")
        else:
            p.add_argument("--step", type=float, default=2.0, help="忽略；sweep 固定扫描")
            p.add_argument("--levels", type=int, default=10, help="忽略")
        p.set_defaults(func=func)

    d = sub.add_parser("demo", help="离线自检（用本地缓存）")
    d.set_defaults(func=cmd_demo)

    args = ap.parse_args()
    if args.data_dir:
        global DATA
        DATA = Path(args.data_dir)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
