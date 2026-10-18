"""Server-side renderer independent of desktop GUI and credentials."""
import io
import json
import os
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
RENDER_LOCK = threading.Lock()

@lru_cache(maxsize=1)
def load_snapshot():
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

def resolve_stock(query, snapshot):
    query = "".join(query.split()).casefold()
    matches = [s for s in snapshot["stocks"] if query in {
        "".join(value.split()).casefold()
        for value in (s["code"], s["name"], *s.get("aliases", []))
    }]
    return matches[0] if len(matches) == 1 else None

def fetch_candles(symbol):
    """Fresh provider daily data, not a guaranteed realtime exchange feed."""
    import pandas as pd
    import requests
    r = requests.get("https://fchart.stock.naver.com/sise.nhn", params={
        "symbol": symbol, "timeframe": "day", "count": "10000", "requestType": "0"
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

def render_chart(stock, snapshot):
    df = fetch_candles(stock["code"])
    with RENDER_LOCK:
        return render_candles(stock, snapshot.get("drawings", {}).get(stock["code"], []), df)

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
        ax.plot(x, df.Close.ewm(span=p, adjust=False).mean().iloc[first:], color=c, linewidth=.8, label=f"EMA{p}")
    dates = {d.strftime("%Y-%m-%d"): i for i,d in enumerate(df.index)}
    skipped = 0
    for d in drawings:
        try:
            values = line_values(d, dates, first, len(df)-1)
            if values is None or not np.isfinite(values).all():
                skipped += 1
                continue
            ax.plot([0,len(sub)-1], values, color=d.get("color","#D97706"), linewidth=1.3, linestyle="--")
        except (ValueError, KeyError, TypeError):
            skipped += 1
    low, high = sub.Low.min(), sub.High.max()
    pad = max((high-low)*.08, high*.01, 1)
    ax.set_ylim(low-pad, high+pad)
    ax.set_xlim(-1,len(sub))
    ax.set_title(f"{stock['name']} ({stock['code']}) | {sub.Close.iloc[-1]:,.0f} KRW | {sub.index[-1]:%Y-%m-%d}", fontproperties=title_font)
    ax.legend(loc="upper left", fontsize=8)
    vol.bar(x, sub.Volume, color=colors, width=.65)
    ticks = np.unique(np.linspace(0,len(sub)-1,min(7,len(sub))).astype(int))
    vol.set_xticks(ticks, [sub.index[i].strftime("%y-%m-%d") for i in ticks])
    for axis in (ax,vol):
        axis.grid(alpha=.2)
        axis.tick_params(labelsize=8)
        axis.ticklabel_format(axis="y", style="plain", useOffset=False)
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    fig.text(.08,.015,f"Fetched {now:%Y-%m-%d %H:%M:%S} KST | Naver daily (may be delayed) | HTS lines: {len(drawings)-skipped}, skipped: {skipped}",fontsize=7)
    fig.subplots_adjust(left=.09,right=.97,top=.92,bottom=.10,hspace=.12)
    buf = io.BytesIO()
    fig.savefig(buf,format="png")
    return buf.getvalue()
