"""权益曲线图：品牌页眉 + 曲线 + 回撤 + 绩效信息表 + 风险提示。

设计约束：
- **matplotlib 是可选依赖**：没装就返回 None，回测本身照常跑；
- 数字全部来自 `metrics.compute` 的同一份结果，不在这里重算，避免图与报告打架；
- 视觉跟 finansi.work 同一套令牌（纸底 / 墨色 / lime），页眉右上角是 FinanSI 标志；
- 底部固定风险提示，不让读者把历史统计当成未来收益。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import brand

DISCLAIMER = "历史回测数据仅供参考，非投资建议。"

# 中文字体候选：Windows / macOS / Linux 各挑一个，最后兜底 DejaVu（无中文）
_FONTS = ("Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC",
          "Source Han Sans SC", "WenQuanYi Zen Hei", "SimHei", "DejaVu Sans")

_GRID = "#ece6d8"        # 纸底上的网格线：只要能看出格，不抢数据
_HAIRLINE = "#cfc8b8"    # 跌破不破的极淡参考线


def _fmt(value: float, kind: str) -> str:
    if kind == "pct_signed":
        return f"{value:+.2%}"
    if kind == "pct":
        return f"{value:.2%}"
    return f"{value:.2f}"


def kpi_items(m: dict) -> list[tuple[str, str, str]]:
    """绩效信息表的 7 项：标签、显示值、颜色。数字全部取自 metrics。"""
    trades = int(m.get("trades") or 0)
    payoff = float(m.get("payoff") or 0.0)
    total = float(m.get("total_return") or 0.0)
    cagr = float(m.get("cagr") or 0.0)
    return [
        ("累计收益率", _fmt(total, "pct_signed"), brand.UP if total >= 0 else brand.DOWN),
        ("年化收益率", _fmt(cagr, "pct_signed"), brand.UP if cagr >= 0 else brand.DOWN),
        ("最大回撤", _fmt(float(m.get("max_dd") or 0.0), "pct"), brand.INK),
        ("年化波动率", _fmt(float(m.get("volatility") or 0.0), "pct"), brand.INK),
        ("夏普比率", _fmt(float(m.get("sharpe") or 0.0), "num"), brand.INK),
        ("胜率", f"{float(m.get('win_rate') or 0.0):.1%}" if trades else "—", brand.INK),
        ("盈亏比", f"{payoff:.2f}" if trades and payoff else "—", brand.INK),
    ]


def draw_kpi(fig, metrics: dict, rect: tuple[float, float, float, float] = (0.050, 0.072, 0.900, 0.112)):
    """绩效信息表：一排 7 格。自定义图也能直接调用，数字同样来自 metrics。"""
    axk = fig.add_axes(list(rect))
    items = kpi_items(metrics)
    axk.set_facecolor(brand.CARD)
    axk.set_xlim(0, len(items))
    axk.set_ylim(0, 1)
    axk.set_xticks([])
    axk.set_yticks([])
    for side in axk.spines:
        axk.spines[side].set_visible(side == "top")
        if side == "top":
            axk.spines[side].set_color(brand.LINE)
            axk.spines[side].set_linewidth(1.0)
    for i, (label, value, color) in enumerate(items):
        x = i + 0.5
        axk.text(x, 0.66, label, ha="center", va="center", fontsize=8.8, color=brand.MUTED)
        axk.text(x, 0.25, value, ha="center", va="center", fontsize=15.5,
                 fontweight="bold", color=color)
        if i:
            axk.axvline(i, ymin=0.12, ymax=0.88, color=brand.LINE_SOFT, lw=0.9)
    return axk


def draw_header(fig, *, title: str = "", desc: str = "", period: str = "",
                series: list[tuple] | None = None,
                font_family: str = "Microsoft YaHei") -> None:
    """页眉：品牌边 + 标志 + 名称 / 策略 / 区间 + 横向图例。

    series 是 [(颜色, 线型, 标签), ...]，放在标题区左下方，不压住走势图。
    """
    from matplotlib.lines import Line2D

    brand.draw_top_rule(fig)
    brand.draw_lockup(fig, 0.965, 0.958, size_in=0.30, fontsize=13.5, anchor="right")

    if title:
        fig.text(0.072, 0.972, title, fontsize=17, fontweight="bold",
                 color=brand.INK, ha="left", va="top")

    def labeled(label: str, text: str, y: float, fontsize: float, color: str) -> None:
        """「策略 / 区间」加粗做小标签，内容另行缩进，避免双冒号读着别扭。"""
        if not text:
            return
        head = f"{label}："
        fig.text(0.072, y, head, fontsize=fontsize, fontweight="bold",
                 color=brand.INK_SOFT, ha="left", va="top")
        # 全角字符按 1em 推进算宽度：TextPath 量的是墨迹，会把冒号后半格吃掉，
        # 内容就会顶到冒号上。标签是固定的两个字，直接用字数算最稳。
        adv = len(head) * fontsize / 72.0 / fig.get_size_inches()[0]
        fig.text(0.072 + adv + 0.002, y, text, fontsize=fontsize, color=color,
                 ha="left", va="top")

    labeled("策略", desc, 0.923, 10.5, brand.INK_SOFT)
    labeled("区间", period, 0.886, 9.5, brand.MUTED)

    if series:
        handles = [Line2D([0], [0], color=c, lw=1.9, ls=ls or "-", label=lb)
                   for c, ls, lb in series]
        fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.066, 0.856),
                   ncol=len(handles), frameon=False, fontsize=9.5,
                   handlelength=2.4, columnspacing=2.2, borderaxespad=0.0)


def render(path: str | Path, equity: pd.Series, metrics: dict, *,
           title: str = "", desc: str = "", period: str = "",
           benchmark: pd.Series | None = None,
           disclaimer: str = DISCLAIMER, dpi: int = 150) -> Path | None:
    """画一张回测图并保存。返回路径；matplotlib 不可用时返回 None。

    title  标题（公司名 + 代码）
    desc   策略描述（标题与区间之间那一行）
    period 回测区间 + 复权口径（口径只写「后复权」）
    """
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
        from matplotlib import font_manager
    except Exception:  # noqa: BLE001 - 没装 matplotlib 就不画图
        return None

    eq = pd.Series(list(map(float, equity.values)),
                   index=pd.Index(pd.to_datetime([str(d)[:10] for d in equity.index])))
    if len(eq) < 2:
        return None

    bench = None
    if benchmark is not None and len(benchmark):
        bench = pd.Series(list(map(float, benchmark.values)),
                          index=pd.Index(pd.to_datetime([str(d)[:10] for d in benchmark.index])))
        bench = bench.reindex(eq.index).ffill()

    available = {f.name for f in font_manager.fontManager.ttflist}
    family = next((f for f in _FONTS if f in available), "DejaVu Sans")
    rc = {"font.family": "sans-serif", "font.sans-serif": [family, "DejaVu Sans"],
          "axes.unicode_minus": False}

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with plt.rc_context(rc):
        fig = plt.figure(figsize=(11, 8.6), dpi=dpi)
        fig.patch.set_facecolor(brand.PAPER)
        ax1 = fig.add_axes([0.072, 0.425, 0.893, 0.375])
        ax2 = fig.add_axes([0.072, 0.245, 0.893, 0.130], sharex=ax1)

        # ── 页眉：品牌边 + 标志 + 名称 / 策略 / 区间 + 图例 ──────
        series = [(brand.UP, None,
                   f"策略收益 {_fmt(float(metrics.get('total_return') or 0), 'pct_signed')}")]
        if bench is not None:
            b_ret = float(bench.iloc[-1] / bench.iloc[0] - 1)
            series.append((brand.BENCH, (0, (5, 2)),
                           f"买入持有 {_fmt(b_ret, 'pct_signed')}"))
        draw_header(fig, title=title, desc=desc, period=period, series=series,
                    font_family=family)

        # ── 权益 ──────────────────────────────────────────────
        ax1.plot(eq.index, eq.values, color=brand.UP, lw=1.9, zorder=3)
        if bench is not None:
            ax1.plot(bench.index, bench.values, color=brand.BENCH, lw=1.3,
                     ls=(0, (5, 2)), zorder=2)
        ax1.axhline(float(eq.iloc[0]), color=_HAIRLINE, lw=0.9, ls=(0, (4, 3)), zorder=1)
        ax1.set_ylabel("权益（元）", fontsize=9.5, color=brand.MUTED)
        ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v / 1e4:.0f}万"))

        # ── 回撤 ──────────────────────────────────────────────
        dd = eq / eq.cummax() - 1
        ax2.fill_between(dd.index, dd.values * 100, 0, color=brand.UP, alpha=0.22, lw=0)
        ax2.plot(dd.index, dd.values * 100, color=brand.UP, lw=0.8, alpha=0.75)
        ax2.set_ylabel("回撤（%）", fontsize=9.5, color=brand.MUTED)
        low = float(dd.min() * 100)
        ax2.set_ylim(min(low * 1.18, -1.0), 1.0)
        ax2.axhline(0, color=_GRID, lw=0.9)

        for ax in (ax1, ax2):
            ax.set_facecolor("none")
            ax.grid(axis="y", color=_GRID, lw=0.8)
            ax.set_axisbelow(True)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            for side in ("left", "bottom"):
                ax.spines[side].set_color(brand.LINE)
            ax.tick_params(colors=brand.MUTED, labelsize=8.5, length=0)
        ax1.tick_params(labelbottom=False)
        ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%y/%m"))

        # ── 绩效信息表 ────────────────────────────────────────
        draw_kpi(fig, metrics)

        # ── 落款：风险提示 ───────────────────────────────────
        fig.text(0.5, 0.030, disclaimer, ha="center", va="center",
                 fontsize=9, color=brand.MUTED)

        fig.savefig(out, dpi=dpi, facecolor=brand.PAPER)
        plt.close(fig)

    return out
