"""FinanSI 品牌元素：配色、标志（mark + wordmark）、图表落款。

视觉直接取自 finansi.work 的站点令牌，不另起一套：
- 配色：`--bg #f4f1e9` / `--ink #121313` / `--lime #f4ff71` / `--card #fbfaf6` / `--muted-ink #666962`
- 标志：`components/brand.tsx` 的 `.logo-mark`——30×30 圆角墨块，中间嵌 18×18 的三根柱
  （lime / 纸白 / lime），柱宽 2.2、圆头；wordmark「FinanSI」里 SI 用灰。

这里只做两件事：把标志画进 matplotlib 图里（矢量，不依赖图片文件），以及导出 SVG。
"""
from __future__ import annotations

from pathlib import Path

# ── 品牌色（与站点 CSS 变量一一对应）─────────────────────────────────
PAPER = "#f4f1e9"        # --bg
PAPER_DEEP = "#e8e4da"   # --bg-deep
CARD = "#fbfaf6"         # --card
INK = "#121313"          # --ink
INK_SOFT = "#3d3e3a"     # --ink-soft
MUTED = "#666962"        # --muted-ink
LIME = "#f4ff71"         # --lime
LIME_DEEP = "#e3f043"    # --lime-deep
LINE = "#d9d3c5"         # --rule 在纸底上的实色
LINE_SOFT = "#ebe7de"    # --muted
BAR_WHITE = "#f8f6ef"

# wordmark 里「SI」的强调色：把 lime 压暗成橄榄（纸底可读），墨底再提亮
SI_LIGHT = "#6f7d2b"
SI_DARK = "#c2d05a"

# ── 行情色：A 股红涨绿跌，跟站点调色不冲突 ───────────────────────────
UP = "#c0392b"
DOWN = "#0f7b4f"
BENCH = "#8d8b83"

# ── 字体：站点用 Bricolage Grotesque（woff2，matplotlib 吃不了），
#    回落到系统里最接近的几何无衬线 ─────────────────────────────────
BRAND_FONT = ("Segoe UI", "Microsoft YaHei", "DejaVu Sans")
MONO_FONT = ("Consolas", "DejaVu Sans Mono", "monospace")

# ── 标志几何：站点 OG 版的三根柱（44 单位方块），比导航栏那版更饱满，
#    小尺寸到大尺寸都能撑住 ──────────────────────────────────────────
BAR_X = (13 / 44, 22 / 44, 31 / 44)          # 0.2955 / 0.5000 / 0.7045
BAR_TOP = (1 - 21 / 44, 1 - 11 / 44, 1 - 17 / 44)   # 0.5227 / 0.7500 / 0.6136
BAR_BASE = 1 - 30 / 44                       # 0.3182
BAR_W = 3 / 44                               # 0.0682
MARK_RADIUS = 13 / 44                        # 0.2955


def text_width_in(text: str, fontsize: float, weight: str = "bold",
                  family: tuple[str, ...] | list[str] | None = None) -> float:
    """量一段文字的宽度（英寸），用于手工排版，比如 wordmark 分段上色。

    含中文时必须把实际渲染用的中文字体传进来：TextPath 只认第一个可用字体，
    Segoe UI 里没有汉字，量出来会偏窄（标签和内容就会贴在一起）。
    """
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath

    fp = FontProperties(family=list(family or BRAND_FONT), weight=weight, size=fontsize)
    return TextPath((0, 0), text, prop=fp).get_extents().width / 72.0


def draw_mark(fig, x: float, y: float, size_in: float, *, dark: bool = False, zorder: int = 20):
    """在 figure 坐标 (x, y) 画一个中心对齐的标志方块，size_in 为边长（英寸）。"""
    from matplotlib.patches import FancyBboxPatch

    fw, fh = fig.get_size_inches()
    w, h = size_in / fw, size_in / fh
    ax = fig.add_axes([x - w / 2, y - h / 2, w, h], zorder=zorder)
    ax.set_axis_off()
    ax.patch.set_alpha(0.0)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    ax.add_patch(FancyBboxPatch(
        (0, 0), 1, 1, boxstyle=f"round,pad=0,rounding_size={MARK_RADIUS}",
        facecolor=PAPER if dark else INK, edgecolor="none",
        transform=ax.transAxes, clip_on=False))

    bars = (LIME, INK if dark else BAR_WHITE, LIME)
    lw = BAR_W * size_in * 72
    for cx, top, color in zip(BAR_X, BAR_TOP, bars):
        ax.plot([cx, cx], [BAR_BASE, top], color=color, lw=lw,
                solid_capstyle="round", transform=ax.transAxes, clip_on=False)
    return ax


def draw_lockup(fig, x: float, y: float, *, size_in: float = 0.32,
                fontsize: float = 14, dark: bool = False, anchor: str = "left",
                si_color: str | None = None, si_highlight: str | None = None):
    """标 + wordmark 组合。(x, y) 为锚点中心线；anchor=right 时 x 是右边界。

    si_color      覆盖「SI」的字色（默认纸底灰 #666962 / 墨底 #a9a79f）
    si_highlight  给「SI」垫一块色块、字反白（用于需要真实 lime 的场合）
    """
    from matplotlib.patches import Rectangle

    fw = fig.get_size_inches()[0]
    fh = fig.get_size_inches()[1]
    # TextPath 量的是字形包围盒，不含右侧字边距，Finan|SI 直接拼会贴死，
    # 补 0.09em 的字距（站点 wordmark 是 -0.035em 的紧排，但不该粘连）。
    track = fontsize * 0.09 / 72.0
    w_finan = text_width_in("Finan", fontsize)
    w_si = text_width_in("SI", fontsize)
    gap = size_in * 0.28
    total = size_in + gap + w_finan + track + w_si
    left = (x - total / fw) if anchor == "right" else x

    draw_mark(fig, left + (size_in / 2) / fw, y, size_in, dark=dark)
    tx = left + (size_in + gap) / fw
    x_si = tx + (w_finan + track) / fw

    if si_highlight:
        pad_l = fontsize * 0.05 / 72.0
        pad_r = fontsize * 0.14 / 72.0
        box_h = fontsize * 1.16 / 72.0
        fig.add_artist(Rectangle((x_si - pad_l / fw, y - (box_h / 2) / fh),
                                 (w_si + pad_l + pad_r) / fw, box_h / fh,
                                 transform=fig.transFigure, facecolor=si_highlight,
                                 edgecolor="none", zorder=9))

    fig.text(tx, y, "Finan", fontsize=fontsize, fontweight="bold",
             color=PAPER if dark else INK, ha="left", va="center",
             fontfamily=list(BRAND_FONT))
    fig.text(x_si, y, "SI", fontsize=fontsize, fontweight="bold",
             color=si_color or (INK if si_highlight else (SI_DARK if dark else SI_LIGHT)),
             ha="left", va="center", fontfamily=list(BRAND_FONT), zorder=10)


def draw_top_rule(fig, height: float = 0.0065):
    """站点 OG 图顶部那道 lime 横条，图表沿用它做品牌边。"""
    from matplotlib.patches import Rectangle

    fig.add_artist(Rectangle((0, 1 - height), 1, height, transform=fig.transFigure,
                             facecolor=LIME, edgecolor="none", zorder=50))


def draw_footer_brand(fig, x: float = 0.072, y: float = 0.030):
    """左下角落款：字号小、单色，不抢正文。"""
    fig.text(x, y, "FinanSI · finansi.work", fontsize=8.5, color=MUTED,
             ha="left", va="center", fontfamily=list(MONO_FONT))


# ── SVG 导出 ────────────────────────────────────────────────────────
def _svg_mark(size: int = 64, dark: bool = False) -> str:
    s = size
    bars = []
    for cx, top, color in zip(BAR_X, BAR_TOP, (LIME, INK if dark else BAR_WHITE, LIME)):
        x = round(cx * s, 2)
        y1 = round((1 - BAR_BASE) * s, 2)
        y2 = round((1 - top) * s, 2)
        bars.append(f'  <path d="M{x} {y1}V{y2}" stroke="{color}" '
                    f'stroke-width="{round(BAR_W * s, 2)}" stroke-linecap="round"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" '
        f'viewBox="0 0 {s} {s}">\n'
        f'  <rect width="{s}" height="{s}" rx="{round(MARK_RADIUS * s, 2)}" '
        f'fill="{PAPER if dark else INK}"/>\n'
        + "\n".join(bars) + "\n</svg>\n")


def write_assets(out_dir: str | Path) -> list[Path]:
    """导出 mark / 浅底组合 / 深底组合 三份 SVG。返回写出的路径。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def lockup(dark: bool) -> str:
        mark = _svg_mark(64, dark=dark)
        mark_body = "\n".join("    " + ln for ln in mark.splitlines()[1:-1])
        word = PAPER if dark else INK
        si = SI_DARK if dark else SI_LIGHT
        plate = (f'\n  <rect width="248" height="64" fill="{INK}"/>' if dark else "")
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="248" height="64" '
            f'viewBox="0 0 248 64">{plate}\n'
            f'  <g>\n{mark_body}\n  </g>\n'
            f'  <text x="80" y="42" font-family="Bricolage Grotesque, Segoe UI, sans-serif" '
            f'font-size="30" font-weight="700" letter-spacing="-1" fill="{word}">Finan'
            f'<tspan fill="{si}">SI</tspan></text>\n'
            "</svg>\n")

    paths = []
    for name, content in (("finansi-mark.svg", _svg_mark(64)),
                          ("finansi-mark-dark.svg", _svg_mark(64, dark=True)),
                          ("finansi-logo.svg", lockup(False)),
                          ("finansi-logo-dark.svg", lockup(True))):
        p = out / name
        p.write_text(content, encoding="utf-8")
        paths.append(p)
    return paths
