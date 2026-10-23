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
    skipped = 0
    for drawing in drawings:
        try:
            values = line_values(drawing, dates, latest, latest)
            if values is None or not math.isfinite(values[1]) or values[1] <= 0:
                skipped += 1
                continue
            gap = (close-values[1])/values[1]*100
            # A line above the current price is not an intact support.
            if not (0 <= gap <= threshold + 1e-9):
                continue
            support = support_evidence(drawing, df, dates)
            if support is not None and (nearest is None or gap < nearest):
                nearest = gap
                evidence = support
        except (KeyError, ValueError, TypeError, OverflowError):
            skipped += 1
    result = None if nearest is None else {
        "code": stock["code"], "name": stock["name"], "gap": nearest,
        "date": df.index[-1].strftime("%Y-%m-%d"), **evidence}
    return result, skipped, df.index[-1].strftime("%Y-%m-%d")


def scan_recommendations(snapshot):
    started = perf_counter()
    stocks = {s["code"]: s for s in snapshot["stocks"]}
    targets = {code: [d for d in drawings if d.get("type") == "trendline"]
               for code, drawings in snapshot.get("drawings", {}).items()
               if code not in {"KOSPI", "KOSDAQ"} and code in stocks}
    targets = {code: drawings for code, drawings in targets.items() if drawings}
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
    lines = ["🔎 이런 종목을 살펴보세요", "━" * 16,
             "과거에 가격이 내려오다 멈추고 다시 오른 차트 선을 찾아봤어요.",
             "그런 움직임이 2번 이상 있었고, 최근에는 크게 깨지지 않은 선이에요.",
             "지금 가격이 그 선보다 1% 이내로 조금 위에 있는 종목을 모았어요.", ""]
    if scan["dates"]:
        lines.append("📅 가격 확인 날짜  " + " ~ ".join(dict.fromkeys([scan["dates"][0], scan["dates"][-1]])))
    if scan["results"]:
        lines.extend(["", f"🌱 살펴볼 종목 {len(scan['results'])}개", "그 선에 가까운 순서예요. 더 잘 오를 순서는 아니에요.", ""])
        for i, r in enumerate(scan["results"], 1):
            lines.append(f"{i:02d}  {r['name']}  ·  {r['code']}")
            detail = f"    ↳ 가격을 받쳐줄지 볼 선보다 {r['gap']:.2f}% 위"
            if 'support_tests' in r:
                detail += f"\n    ↳ 선 근처에서 멈췄다가 다시 오른 기록 {r['support_tests']}번"
            lines.extend([detail, ""])
    elif scan["total"] == 0:
        lines.extend(["", "📂 분석에 사용할 차트 선이 아직 없어요.", "HTS에서 그린 선을 동기화해 주세요."])
    elif scan["failed"] == scan["total"]:
        lines.extend(["", "📡 현재 가격을 불러오지 못했어요.", "잠시 후 다시 요청해 주세요."])
    else:
        lines.extend(["", "🌿 확인한 종목 중 지금 조건에 맞는 종목은 없어요.", "과거에 가격을 받쳐준 선 가까이 내려온 종목이 있는지 다음에 다시 살펴보세요."])
    if scan["results"]:
        lines.extend(["💡 목록에 있다고 바로 사지는 마세요.",
                      "가격이 그 선 근처에서 멈추고 다시 오르는지 먼저 확인하세요.",
                      "아래 종목 버튼을 누르면 차트와 설명을 볼 수 있어요.", ""])
    lines.extend(["━" * 16, f"📊 살펴본 종목 {scan['total']}개 · 가격을 못 불러온 종목 {scan['failed']}개",
                  f"계산할 수 없는 선 {scan['skipped']}개는 제외했어요.",
                  f"🕒 조회 {scan['checked_at']} KST · 제공처 최신 일봉 가격 기준",
                  "※ 장이 열려 있으면 가격은 바뀌어요. 선 아래로 더 떨어지거나 손실이 날 수도 있어요."])
    return "\n".join(lines)
