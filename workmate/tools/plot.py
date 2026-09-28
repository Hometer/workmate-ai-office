"""plot_chart：本地确定性画图（matplotlib）。"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang SC", "Heiti SC", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False


def plot_trend(df: pd.DataFrame, date_col, sales_col, out_path: Path) -> None:
    d = pd.to_datetime(df[date_col], errors="coerce")
    mask = d.notna()
    s = df.loc[mask].assign(_d=d[mask].dt.date).groupby("_d")[sales_col].sum().sort_index()
    plot_trend_series(s, out_path)


def plot_trend_series(daily, out_path: Path) -> None:
    plt.figure(figsize=(8, 4))
    plt.plot(daily.index.astype(str), daily.values, marker="o")
    plt.title("销售趋势")
    plt.xlabel("日期")
    plt.ylabel("销售额")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()


def plot_top5(top5: list[dict], out_path: Path) -> None:
    names = [item["name"] for item in top5]
    values = [item["sales"] for item in top5]
    plt.figure(figsize=(8, 4))
    plt.bar(names, values)
    plt.title("Top5 商品销售额")
    plt.ylabel("销售额")
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()


def plot_channel(channel_share: list[dict], out_path: Path) -> None:
    labels = [item["name"] for item in channel_share]
    shares = [item["share"] for item in channel_share]
    plt.figure(figsize=(6, 6))
    plt.pie(shares, labels=labels, autopct="%1.1f%%")
    plt.title("渠道占比")
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()


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
