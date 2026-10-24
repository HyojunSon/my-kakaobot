"""Screen saved trendlines against fresh daily closes."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import logging
import math
from time import perf_counter
from zoneinfo import ZoneInfo

from api.chart_service import fetch_candles, history_count, line_values

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def support_evidence(drawing, df, dates):
    """Conservative heuristic: held from above and rebounded on separate visits.

    Excludes the latest (possibly incomplete) candle from historical evidence.
    Uses session-specific line prices, never a constant level for a sloped line.
    """
    if drawing.get("type") != "trendline":
        return None
    anchors = [dates.get(drawing.get(k)) for k in ("start_date", "end_date")]
    if any(x is None for x in anchors):
        return None
    start = max(0, len(df)-61, min(anchors)+1)
    stop = len(df)-1
    if stop-start < 20:
        return None
    first, final = line_values(drawing, dates, start, stop-1)
    step = (final-first)/(stop-1-start)
    prices = [first+step*i for i in range(stop-start)]
    if any(not math.isfinite(p) or p <= 0 for p in prices):
        return None
    closes = [float(x) for x in df.Close.iloc[start:stop]]
    lows = [float(x) for x in df.Low.iloc[start:stop]]
    if any(not math.isfinite(v) for v in closes+lows):
        return None
    held = sum(c >= p*.998 for c,p in zip(closes, prices))/len(prices)
    if held < .8 or any(c < p*.995 for c,p in zip(closes[-3:], prices[-3:])):
        return None
    touches = 0
    last_touch = -4
    for i in range(len(prices)-1):
        if i-last_touch < 3:
            continue
        # A low visits the line, the candle recovers above it, then a later
        # candle closes >=0.5% above its own line without an intervening break.
        if abs(lows[i]/prices[i]-1) <= .005 and closes[i] >= prices[i]:
            for j in range(i+1, min(i+4, len(prices))):
                if closes[j] < prices[j]*.995:
                    break
                if closes[j] >= prices[j]*1.005:
                    touches += 1
                    last_touch = j  # Do not count one prolonged visit twice.
                    break
    if touches < 2:
        return None
    return {"support_tests": touches, "held_ratio": held}


def check_symbol(stock, drawings, threshold=1.0):
    df = fetch_candles(stock["code"], count=history_count(drawings))
    if df.empty:
        raise ValueError("Empty candles")
    dates = {date.strftime("%Y-%m-%d"): i for i, date in enumerate(df.index)}
    latest = len(df)-1
    close = float(df.Close.iloc[-1])
    if not math.isfinite(close) or close <= 0:
        raise ValueError("Invalid close")
    nearest = None
    evidence = None
    selected_price = None
    selected_id = None
    levels = []
    skipped = 0
    for drawing in drawings:
        try:
            values = line_values(drawing, dates, latest, latest)
            if values is None or not math.isfinite(values[1]) or values[1] <= 0:
                skipped += 1
                continue
            levels.append((drawing.get("id"), values[1]))
            if drawing.get("type") != "trendline":
                continue
            gap = (close-values[1])/values[1]*100
            # Historical support can be slightly below OR above the latest
            # price. Below-support candidates explicitly require recovery.
            if abs(gap) > threshold + 1e-9:
                continue
            support = support_evidence(drawing, df, dates)
            if support is not None and (nearest is None or abs(gap) < abs(nearest)):
                nearest = gap
                evidence = support
                selected_price = values[1]
                selected_id = drawing.get("id")
        except (KeyError, ValueError, TypeError, OverflowError):
            skipped += 1
    resistance = min((price for _, price in levels if selected_price is not None
                      and price > max(selected_price, close)), default=None)
    result = None if nearest is None else {
        "code": stock["code"], "name": stock["name"], "gap": nearest,
        "current_price": close, "support_price": selected_price, "support_line_id": selected_id,
        "position": "below" if nearest < -1e-9 else ("above" if nearest > 1e-9 else "on"),
        "resistance_price": resistance,
        "expected_return_pct": (resistance/selected_price-1)*100 if resistance is not None else None,
        "date": df.index[-1].strftime("%Y-%m-%d"), **evidence}
    return result, skipped, df.index[-1].strftime("%Y-%m-%d")


def scan_recommendations(snapshot):
    started = perf_counter()
    stocks = {s["code"]: s for s in snapshot["stocks"]}
    targets = {code: drawings
               for code, drawings in snapshot.get("drawings", {}).items()
               if code not in {"KOSPI", "KOSDAQ"} and code in stocks
               and any(d.get("type") == "trendline" for d in drawings)}
    results, failed, skipped, dates = [], 0, 0, set()
    # No GUI, indicators or rendering. Fetch independent symbols concurrently.
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(check_symbol, stocks[code], drawings): code
                   for code, drawings in targets.items()}
        for future in as_completed(futures):
            try:
                result, missing, date = future.result()
                skipped += missing
                dates.add(date)
                if result is not None:
                    results.append(result)
            except Exception:
                failed += 1
                logger.exception("recommendation_fetch_failed symbol=%s", futures[future])
    results.sort(key=lambda r: (abs(r["gap"]), r["code"]))
    logger.info("recommendation_timing targets=%d matched=%d failed=%d skipped_lines=%d total_ms=%.1f",
                len(targets), len(results), failed, skipped, (perf_counter()-started)*1000)
    return {"results": results, "total": len(targets), "failed": failed,
            "skipped": skipped, "dates": sorted(dates),
            "checked_at": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m-%d %H:%M")}


def recommendation_text(scan):
    lines = ["🔎 지금 살펴볼 종목"]
    if scan["dates"]:
        lines.append("📅 " + " ~ ".join(dict.fromkeys([scan["dates"][0], scan["dates"][-1]])))
    if scan["results"]:
        lines.append(f"🌱 총 {len(scan['results'])}종목")
        for i, r in enumerate(scan["results"], 1):
            lines.append(f"• {r['name']} ({r['code']})")
            if "position" in r:
                lines.append("  🟠 지지선 아래: 다시 선 위로 회복하는지 확인하세요."
                             if r["position"] == "below" else "  🟢 지지선 위·접촉: 가격이 버티는지 확인하세요.")
                if r["resistance_price"] is not None:
                    lines.append(f"  지지 {r['support_price']:,.0f}원 → 저항 {r['resistance_price']:,.0f}원 · 예상 +{r['expected_return_pct']:.1f}%")
                else:
                    lines.append(f"  지지 {r['support_price']:,.0f}원 · 위쪽 저항선 없어 수익률 계산 보류")
    elif scan["total"] == 0:
        lines.append("📂 아직 분석할 종목이 없어요.")
    elif scan["failed"] == scan["total"]:
        lines.extend(["", "📡 현재 가격을 불러오지 못했어요.", "잠시 후 다시 요청해 주세요."])
    else:
        lines.append("🌿 지금은 추천할 종목이 없어요. 잠시 후 다시 확인해 주세요.")
    if scan["results"]:
        lines.append("📈 아래 종목 버튼으로 차트와 분석을 확인하세요.")
    if scan["failed"]:
        lines.append(f"일부 종목({scan['failed']}개)은 시세를 확인하지 못했어요.")
    lines.extend([f"🕒 {scan['checked_at']} KST",
                  "※ 수익률은 현재 선 가격 간 단순 계산(비용 제외)이며 보장 수익이 아니에요."])
    return "\n".join(lines)
