"""本地确定性图表：独立画布、统一中文字体与报告口径。"""
from __future__ import annotations

from functools import wraps
from pathlib import Path
from threading import RLock
import textwrap

import matplotlib
matplotlib.use("Agg")
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib import font_manager
from matplotlib.figure import Figure
from matplotlib.text import Text
from matplotlib.ticker import FuncFormatter
import pandas as pd

_FONT_NAMES = {font.name for font in font_manager.fontManager.ttflist}
_FONTS = [name for name in ("Arial Unicode MS", "PingFang SC", "Heiti SC", "SimHei") if name in _FONT_NAMES] + ["sans-serif"]
_PURPLE, _INK, _MUTED, _GRID = "#7863ca", "#252733", "#5d6472", "#e3e6ec"
# Matplotlib/font rendering is serialized; task computation remains concurrent.
_RENDER_LOCK = RLock()


def _serialized(function):
    @wraps(function)
    def run(*args, **kwargs):
        with _RENDER_LOCK:
            return function(*args, **kwargs)
    return run


def _number(value):
    text = f"{float(value):,.8f}"
    whole, fraction = text.split(".")
    return whole + "." + fraction.rstrip("0").ljust(2, "0")


def _canvas(title, context=None, *, height=5.1):
    ctx = context or {}
    mode = "每行金额相加" if ctx.get("amount_mode") == "A" else "整单金额去重" if ctx.get("amount_mode") == "B" else "见报告口径"
    note = f"金额单位：{ctx.get('unit', '单位待确认')} · {mode} · 计算核对不代表业务数据完整"
    if ctx.get("warnings"):
        note += "；" + "；".join(ctx["warnings"])
    footer = textwrap.wrap(note, width=68) or [note]
    scope = textwrap.wrap(str(ctx.get("scope", "全表")), width=66)
    height += .2 * (len(footer) + len(scope) - 2)
    figure = Figure(figsize=(10, height), facecolor="white")
    FigureCanvasAgg(figure)
    axes = figure.add_subplot(111)
    figure.subplots_adjust(left=.11, right=.96, top=1 - (.95 + .18 * len(scope)) / height, bottom=(.85 + .24 * len(footer)) / height)
    figure.text(.055, 1 - .3 / height, title, fontsize=18, color=_INK, weight="semibold", va="top")
    figure.text(.055, 1 - .66 / height, "\n".join(scope), fontsize=11, color=_MUTED, va="top")
    figure.text(.055, .12 / height, "\n".join(footer), fontsize=10, color=_MUTED, va="bottom")
    axes.set_axisbelow(True)
    axes.tick_params(colors=_MUTED, labelsize=11, length=0, pad=9)
    for spine in axes.spines.values():
        spine.set_visible(False)
    return figure, axes


def _save(figure, out_path):
    for text in figure.findobj(Text):
        text.set_fontfamily(_FONTS)
    figure.savefig(out_path, dpi=140, facecolor="white", bbox_inches="tight", pad_inches=.2)
    figure.clear()


@_serialized
def plot_trend_series(daily, out_path: Path, *, context=None) -> None:
    figure, axes = _canvas("每日销售趋势", context)
    labels = daily.index.astype(str)
    axes.plot(labels, daily.values, color=_PURPLE, marker="o", markersize=5, linewidth=2, markeredgecolor="white")
    axes.fill_between(labels, daily.values, 0, color=_PURPLE, alpha=.08)
    axes.grid(axis="y", color=_GRID, linewidth=.7)
    axes.axhline(0, color="#bdc2cc", linewidth=.7)
    axes.yaxis.set_major_formatter(FuncFormatter(lambda value, _: _number(value)))
    axes.set_ylabel(f"销售额（{(context or {}).get('unit', '单位待确认')}）", color=_MUTED, fontsize=11, labelpad=12)
    if len(daily) > 8:
        every = max(1, len(daily) // 8)
        positions = list(range(0, len(daily), every))
        if positions[-1] != len(daily) - 1:
            positions.append(len(daily) - 1)
        axes.set_xticks(positions, [labels[index] for index in positions], rotation=25, ha="right")
    _save(figure, out_path)


def plot_trend(df: pd.DataFrame, date_col, sales_col, out_path: Path) -> None:
    dates = pd.to_datetime(df[date_col], errors="coerce")
    mask = dates.notna()
    daily = df.loc[mask].assign(_d=dates[mask].dt.date).groupby("_d")[sales_col].sum().sort_index()
    plot_trend_series(daily, out_path)


def _bars(title, labels, values, out_path, context, *, percentage=False):
    names = ["\n".join(textwrap.wrap(str(label), width=18)) for label in labels]
    lines = sum(name.count("\n") + 1 for name in names)
    figure, axes = _canvas(title, context, height=max(5.1, 2.5 + .38 * lines))
    axes.set_position([.28, axes.get_position().y0, .64, axes.get_position().height])
    bars = axes.barh(range(len(names)), values, color=[_PURPLE if value >= 0 else "#b95151" for value in values], height=.5)
    axes.set_yticks(range(len(names)), names)
    axes.invert_yaxis()
    axes.grid(axis="x", color=_GRID, linewidth=.7)
    axes.axvline(0, color="#bdc2cc", linewidth=.8)
    low, high = min([0, *values]), max([0, *values])
    spread = max(high - low, 1)
    axes.set_xlim(low - spread * .24 if low < 0 else 0, (max(100, high) if percentage else high) + spread * .26)
    for bar, value in zip(bars, values):
        axes.annotate(f"{value:.2f}%" if percentage else _number(value), (value, bar.get_y() + bar.get_height() / 2), xytext=(6 if value >= 0 else -6, 0), textcoords="offset points", va="center", ha="left" if value >= 0 else "right", fontsize=11, color=_INK)
    axes.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}%" if percentage else _number(value)))
    axes.set_xlabel("销售额占比（%）" if percentage else f"销售额（{(context or {}).get('unit', '单位待确认')}）", color=_MUTED, fontsize=11, labelpad=12)
    _save(figure, out_path)


@_serialized
def plot_top5(top5: list[dict], out_path: Path, *, context=None) -> None:
    _bars("Top5 商品销售额", [item["name"] for item in top5], [item["sales"] for item in top5], out_path, context)


@_serialized
def plot_channel(channel_share: list[dict], out_path: Path, *, context=None) -> None:
    # Computation stores 0–1 ratios; the axis and labels display 0–100 percent.
    _bars("渠道销售占比", [item["name"] for item in channel_share], [item["share"] * 100 for item in channel_share], out_path, context, percentage=True)


def plot_charts(df: pd.DataFrame, mapping: dict, metrics: dict, charts_dir: Path) -> list[Path]:
    """按数据可得性画图，缺列则跳过对应图。返回已生成的图片路径列表。"""
    charts_dir = Path(charts_dir)
    charts_dir.mkdir(parents=True, exist_ok=True)
    charts: list[Path] = []
    sales_col = mapping["sales"]
    if mapping.get("date"):
        p = charts_dir / "trend.png"
        plot_trend(df, mapping["date"], sales_col, p)
        charts.append(p)
    if metrics.get("top5"):
        p = charts_dir / "top5.png"
        plot_top5(metrics["top5"], p)
        charts.append(p)
    if metrics.get("channel_share"):
        p = charts_dir / "channel.png"
        plot_channel(metrics["channel_share"], p)
        charts.append(p)
    return charts
