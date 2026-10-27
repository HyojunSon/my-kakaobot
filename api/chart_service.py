"""Server-side renderer independent of desktop GUI and credentials."""
import io
import json
import os
import threading
import logging
from time import perf_counter
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
from api.analysis_store import source_mode, fetch_analysis_rows
import copy

ROOT = Path(__file__).resolve().parent.parent
RENDER_LOCK = threading.Lock()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def history_count(drawings):
    # 1,000 sessions gives EMA120 over 800 warm-up sessions before the
    # visible six months. Calendar days are a conservative session bound.
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    count = 1000
    for drawing in drawings:
        if drawing.get("type") != "trendline":
            continue
        for key in ("start_date", "end_date"):
            try:
                date = datetime.strptime(drawing[key], "%Y-%m-%d").date()
                count = max(count, (today-date).days + 60)
            except (KeyError, ValueError, TypeError):
                continue
    return min(count, 10000)

@lru_cache(maxsize=1)
def _file_snapshot():
    snapshot = json.loads((ROOT / "data/hts_snapshot.json").read_text(encoding="utf-8"))
    catalog_path = ROOT / "data/stock_catalog.json"
    if catalog_path.exists():
        stocks = {s["code"]: s for s in json.loads(catalog_path.read_text(encoding="utf-8"))}
        for stock in snapshot["stocks"]:
            if stock["code"] not in stocks:
                stocks[stock["code"]] = stock
            elif stock["name"] != stock["code"] and stock["name"] != stocks[stock["code"]]["name"]:
                stocks[stock["code"]].setdefault("aliases", []).append(stock["name"])
        snapshot["stocks"] = list(stocks.values())
    return snapshot


def load_snapshot():
    if source_mode() == "snapshot":
        return _file_snapshot()
    snapshot = copy.deepcopy(_file_snapshot())
    rows = fetch_analysis_rows()
    # DB is authoritative, including empty rows and an entirely empty table.
    snapshot["drawings"] = {r["symbol"]: r["drawings"] for r in rows}
    stocks = {s["code"]: s for s in snapshot["stocks"]}
    for row in rows:
        code = row["symbol"]
        name = row.get("name") or code
        if code not in stocks:
            stocks[code] = {"code": code, "name": name}
        elif name != code and name != stocks[code]["name"]:
            stocks[code].setdefault("aliases", []).append(name)
    snapshot["stocks"] = list(stocks.values())
    snapshot["analysis_revisions"] = {r["symbol"]: r["revision"] for r in rows}
    snapshot["exported_at"] = max((r["updated_at"] for r in rows), default=None)
    snapshot["source"] = "supabase"
    return snapshot

def resolve_stock(query, snapshot):
    query = "".join(query.split()).casefold()
    matches = [s for s in snapshot["stocks"] if query in {
        "".join(value.split()).casefold()
        for value in (s["code"], s["name"], *s.get("aliases", []))
    }]
    return matches[0] if len(matches) == 1 else None

def fetch_candles(symbol, count=10000):
    """Fresh provider daily data, not a guaranteed realtime exchange feed."""
    import pandas as pd
    import requests
    r = requests.get("https://fchart.stock.naver.com/sise.nhn", params={
        "symbol": symbol, "timeframe": "day", "count": str(count), "requestType": "0"
    }, timeout=(2, 8), headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    # Naver declares EUC-KR. Expat cannot parse that multibyte encoding
    # directly from bytes; requests decodes the HTTP charset first.
    rows = [n.attrib.get("data", "").split("|")[:6] for n in ET.fromstring(r.text).iter("item")]
    rows = [r for r in rows if len(r) == 6]
    if not rows:
        raise ValueError("No candles")
    df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df.Date, format="%Y%m%d")
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna().drop_duplicates("Date").set_index("Date").sort_index()
    df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]
    if df.empty:
        raise ValueError("No valid candles")
    return df

def line_values(d, dates, start, end):
    if d.get("type") == "horizontal":
        return float(d["price"]), float(d["price"])
    if d.get("type") != "trendline":
        return None
    x1, x2 = dates.get(d["start_date"]), dates.get(d["end_date"])
    if x1 is None or x2 is None or x1 == x2:
        return None
    y1, y2 = float(d["start_price"]), float(d["end_price"])
    slope = (y2-y1)/(x2-x1)
    return y1+slope*(start-x1), y1+slope*(end-x1)

def chart_data(stock, snapshot):
    drawings = snapshot.get("drawings", {}).get(stock["code"], [])
    count = history_count(drawings)
    df = fetch_candles(stock["code"], count=count)
    # If the provider returns fewer sessions than requested, retry the
    # original history range when an older anchor might otherwise be lost.
    earliest = df.index[0].strftime("%Y-%m-%d")
    if count < 10000 and any(
        isinstance(d.get(key), str) and d[key] < earliest
        for d in drawings if d.get("type") == "trendline"
        for key in ("start_date", "end_date")
    ):
        df = fetch_candles(stock["code"], count=10000)
    return df, drawings


def render_chart(stock, snapshot):
    started = perf_counter()
    df, drawings = chart_data(stock, snapshot)
    fetched = perf_counter()
    with RENDER_LOCK:
        acquired = perf_counter()
        png = render_candles(stock, drawings, df)
    finished = perf_counter()
    logger.info("chart_timing symbol=%s candles=%d fetch_ms=%.1f lock_ms=%.1f render_ms=%.1f total_ms=%.1f bytes=%d",
                stock["code"], len(df), (fetched-started)*1000, (acquired-fetched)*1000,
                (finished-acquired)*1000, (finished-started)*1000, len(png))
    return png

def render_candles(stock, drawings, df):
    import tempfile
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "kakaobot-mpl"))
    import numpy as np
    import pandas as pd
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.collections import LineCollection, PolyCollection
    from matplotlib import font_manager
    font = ROOT / "assets/chart-font.ttf"
    if font.exists():
        title_font = font_manager.FontProperties(fname=str(font), size=11)
    else:
        family = next((name for name in ("Malgun Gothic", "NanumGothic", "Noto Sans CJK KR")
                       if any(f.name == name for f in font_manager.fontManager.ttflist)), "DejaVu Sans")
        title_font = font_manager.FontProperties(family=family, size=11)
    first = int(df.index.searchsorted(df.index[-1] - pd.DateOffset(months=6)))
    sub = df.iloc[first:]
    x = np.arange(len(sub))
    colors = np.where(sub.Close >= sub.Open, "#E11D48", "#2563EB")
    fig = Figure(figsize=(10, 6.2), dpi=130, facecolor="white")
    FigureCanvasAgg(fig)
    ax, vol = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [4, 1]})
    ax.add_collection(LineCollection([[(i, r.Low), (i, r.High)] for i, r in enumerate(sub.itertuples())], colors=colors, linewidths=.8))
    bodies = []
    for i, r in enumerate(sub.itertuples()):
        lo, hi = sorted((r.Open, r.Close))
        hi = max(hi, lo + max(r.High-r.Low, 1)*.015)
        bodies.append([(i-.32,lo), (i-.32,hi), (i+.32,hi), (i+.32,lo)])
    ax.add_collection(PolyCollection(bodies, facecolors=colors, edgecolors=colors, linewidths=.5))
    for p, c in [(5,"#F59E0B"),(20,"#DC2626"),(60,"#10B981"),(120,"#6366F1")]:
        ax.plot(x, df.Close.ewm(span=p, adjust=False).mean().iloc[first:], color=c, linewidth=.45, label=f"EMA{p}")
    dates = {d.strftime("%Y-%m-%d"): i for i,d in enumerate(df.index)}
    skipped = 0
    for d in drawings:
        try:
            values = line_values(d, dates, first, len(df)-1)
            if values is None or not np.isfinite(values).all():
                skipped += 1
                continue
            ax.plot([0,len(sub)-1], values, color=d.get("color","#D97706"), linewidth=1.3, linestyle="-")
        except (ValueError, KeyError, TypeError):
            skipped += 1
    low, high = sub.Low.min(), sub.High.max()
    pad = max((high-low)*.08, high*.01, 1)
    ax.set_ylim(low-pad, high+pad)
    ax.set_xlim(-1,len(sub))
    price_label = (f"{sub.Close.iloc[-1]:,.2f} pt" if stock["code"] in {"KOSPI", "KOSDAQ"}
                   else f"{sub.Close.iloc[-1]:,.0f} KRW")
    latest = float(sub.Close.iloc[-1])
    previous = float(df.Close.iloc[-2]) if len(df) > 1 else latest
    price_color = "#E11D48" if latest >= previous else "#2563EB"
    ax.axhline(latest, color=price_color, linewidth=.55, alpha=.4)
    ax.annotate(price_label, xy=(1, latest), xycoords=("axes fraction", "data"),
                xytext=(6, 0), textcoords="offset points", va="center", ha="left",
                fontsize=8, color="white", annotation_clip=False,
                bbox={"boxstyle": "round,pad=.3", "fc": price_color, "ec": "none"}, zorder=10)
    ax.set_title(f"{stock['name']} ({stock['code']}) | {price_label} | {sub.index[-1]:%Y-%m-%d}", fontproperties=title_font)
    ax.legend(loc="upper left", fontsize=8)
    # One collection instead of a Rectangle/artist for every volume bar.
    volumes = sub.Volume.to_numpy()
    volume_vertices = np.empty((len(sub), 4, 2))
    volume_vertices[:, :, 0] = np.column_stack((x-.325, x-.325, x+.325, x+.325))
    volume_vertices[:, :, 1] = np.column_stack((np.zeros(len(sub)), volumes, volumes, np.zeros(len(sub))))
    vol.add_collection(PolyCollection(volume_vertices, facecolors=colors, edgecolors="none"))
    vol.set_ylim(0, max(float(volumes.max())*1.08, 1))
    ticks = np.unique(np.linspace(0,len(sub)-1,min(7,len(sub))).astype(int))
    vol.set_xticks(ticks, [sub.index[i].strftime("%y-%m-%d") for i in ticks])
    for axis in (ax,vol):
        axis.yaxis.tick_right()
        axis.yaxis.set_label_position("right")
        axis.tick_params(axis="y", left=False, labelleft=False, right=True, labelright=True)
        axis.grid(alpha=.2)
        axis.tick_params(labelsize=8)
        axis.ticklabel_format(axis="y", style="plain", useOffset=False)
    # Leave room for the highlighted price instead of overlapping a regular tick.
    minimum, maximum = ax.get_ylim()
    ax.set_yticks([tick for tick in ax.get_yticks()
                  if minimum <= tick <= maximum and abs(tick-latest) > (maximum-minimum)*.035])
    ax.set_ylim(minimum, maximum)
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    fig.text(.04,.015,f"Fetched {now:%Y-%m-%d %H:%M:%S} KST | Naver daily (may be delayed) | HTS lines: {len(drawings)-skipped}, skipped: {skipped}",fontsize=7)
    fig.subplots_adjust(left=.04,right=.86,top=.92,bottom=.10,hspace=.12)
    buf = io.BytesIO()
    fig.savefig(buf,format="png", pil_kwargs={"compress_level": 1})
    return buf.getvalue()
