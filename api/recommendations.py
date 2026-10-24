"""Screen saved trendlines against fresh daily closes."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import logging
import math
from time import perf_counter
from zoneinfo import ZoneInfo

from api.chart_service import fetch_candles, history_count, line_values
from api.line_context import line_context, CONVERGENCE_NOTE
from api.chart_patterns import detect_pattern, pattern_messages

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# Policy parameters are heuristics, not fitted profitability claims.
ROLE_LOOKBACK = 60
SUPPORT_FRESHNESS = 30
TOUCH_TOLERANCE = .005
BOUNCE_CLEARANCE = .005
BREAK_CLEARANCE = .01


def support_evidence(drawing, df, dates):
    """Track recent support visits; a confirmed break resets old evidence.

    Never use the latest, possibly incomplete candle as confirmation. An
    approach from above is eligible for observation before a bounce confirms.
    Each price is compared with its own session's projected line value.
    """
    if drawing.get("type") != "trendline":
        return None
    anchors = [dates.get(drawing.get(k)) for k in ("start_date", "end_date")]
    if any(x is None for x in anchors):
        return None
    # This is current screening of a user-drawn line, not a historical
    # backtest. Its second anchor is not the start of its support role.
    start = max(0, len(df)-ROLE_LOOKBACK-1, min(anchors)+1)
    stop = len(df)-1
    if stop-start < 10:
        return None
    first, final = line_values(drawing, dates, start, stop-1)
    step = (final-first)/(stop-1-start)
    prices = [first+step*i for i in range(stop-start)]
    closes = [float(x) for x in df.Close.iloc[start:stop]]
    lows = [float(x) for x in df.Low.iloc[start:stop]]
    if any(not math.isfinite(p) or p <= 0 for p in prices) or any(
            not math.isfinite(v) for v in closes+lows):
        return None
    gaps = [c/p-1 for c,p in zip(closes, prices)]
    visits = []
    pending = None
    last_confirmation = -4
    reset = -1
    for i, gap in enumerate(gaps):
        # A single >=1% close below, or two consecutive >=0.5% closes
        # below, invalidates all earlier support visits. A later retest can
        # establish a new role; being below the line long ago is irrelevant.
        broken = gap <= -BREAK_CLEARANCE+1e-9 or (
            i > 0 and gap <= -TOUCH_TOLERANCE+1e-9
            and gaps[i-1] <= -TOUCH_TOLERANCE+1e-9)
        if broken:
            visits.clear()
            pending = None
            reset = i
            continue
        if pending is not None:
            if gap < -TOUCH_TOLERANCE or i-pending > 3:
                pending = None
            elif gap >= BOUNCE_CLEARANCE-1e-9:
                visits.append((pending, i))
                last_confirmation = i
                pending = None
        # The approach must come from above: at least two of the prior
        # three closes above the line, after the most recent confirmed break.
        prior = gaps[max(reset+1, i-3):i]
        from_above = sum(g >= .002-1e-9 for g in prior) >= 2
        if (pending is None and i-last_confirmation >= 3 and from_above
                and abs(lows[i]/prices[i]-1) <= TOUCH_TOLERANCE+1e-9
                and gap >= 0):
            pending = i
    recent = [(touch, confirm) for touch, confirm in visits
              if len(prices)-1-confirm < SUPPORT_FRESHNESS]
    if recent:
        return {"support_tests": len(visits), "support_status": "confirmed",
                "last_support_date": df.index[start+recent[-1][1]].strftime("%Y-%m-%d"),
                "support_age_sessions": len(prices)-1-recent[-1][1]}
    # Do not wait for a rebound to finish before flagging a nearby support
    # candidate. Require a recent approach from above after any failed role.
    approach = gaps[max(reset+1, len(gaps)-3):]
    if (len(approach) >= 2 and sum(g >= .002-1e-9 for g in approach) >= 2
            and gaps[-1] >= -.002-1e-9):
        return {"support_tests": 0, "support_status": "awaiting_confirmation",
                "last_support_date": None, "support_age_sessions": None}
    return None


def check_symbol(stock, drawings, threshold=1.0, df=None):
    if df is None:
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
    skipped = 0
    for drawing in drawings:
        try:
            values = line_values(drawing, dates, latest, latest)
            if values is None or not math.isfinite(values[1]) or values[1] <= 0:
                skipped += 1
                continue
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
    context = line_context(drawings, df, selected_price)
    resistance = context["resistance_price"]
    result = None if nearest is None else {
        "code": stock["code"], "name": stock["name"], "gap": nearest,
        "current_price": close, "support_price": selected_price, "support_line_id": selected_id,
        "position": "below" if nearest < -1e-9 else ("above" if nearest > 1e-9 else "on"),
        "resistance_price": resistance,
        "expected_return_pct": (resistance/selected_price-1)*100 if resistance is not None else None,
        "pattern": detect_pattern(df, drawings) if nearest is not None else None,
        "date": df.index[-1].strftime("%Y-%m-%d"), **evidence, **context}
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


def recommendation_text(scan, results=None, start_index=0, page_label=""):
    results = scan["results"] if results is None else results
    lines = ["종목추천" + page_label]
    if scan["dates"]:
        lines.append("기준일 " + " ~ ".join(dict.fromkeys([scan["dates"][0], scan["dates"][-1]])))
    if scan["results"]:
        lines.append(f"총 {len(scan['results'])}종목 · 회복과 안착을 확인하고 판단하세요.")
        for i, r in enumerate(results, start_index+1):
            block_start = len(lines)
            lines.extend(["", "────────────", f"{i}. {r['name']} ({r['code']})"])
            if r.get("support_status") == "awaiting_confirmation":
                lines.append("상태: 지지 확인 대기 · 반등 미확인")
            if "position" in r:
                if r.get("zone_count", 0) >= 2:
                    lines.append(f"선 밀집 구간 {r['zone_low']:,.0f}원~{r['zone_high']:,.0f}원")
                if r.get("converging"):
                    lines.append(CONVERGENCE_NOTE)
                if "current_price" in r:
                    lines.append(f"현재가 {r['current_price']:,.0f}원")
                lines.append("매수: 지지선 소폭 이탈. 회복하며 올라올 때 지지선 부근을 살펴보세요."
                             if r["position"] == "below" else "매수: 지지선 위·접촉. 가격이 버티는지 확인하세요.")
                if r["resistance_price"] is not None:
                    label = "기준선" if r.get("zone_count", 0) >= 2 else "지지선"
                    lines.append(f"{label} {r['support_price']:,.0f}원 → 저항선 {r['resistance_price']:,.0f}원")
                    lines.append(f"예상 수익률 +{r['expected_return_pct']:.1f}% · {label} 매수 / 저항선 매도 가정")
                else:
                    lines.append(f"지지선 {r['support_price']:,.0f}원 · 위쪽 저항선 없음")
                    lines.append("예상 수익률: 저항선이 없어 계산 보류")
            if r.get("zone_count", 0) >= 2:
                for j in range(block_start, len(lines)):
                    lines[j] = lines[j].replace("지지선", "기준선").replace("지지 확인 대기", "구간 방향 확인 대기")
            pattern_status, pattern_opinion = pattern_messages(r.get("pattern"))
            if r.get("pattern") and r["pattern"]["state"] in {"down_attempt", "down_holding", "failed_up"}:
                for j in range(block_start, len(lines)):
                    if lines[j].startswith("매수:"):
                        lines[j] = "매수: 패턴 하단 이탈·돌파 실패에 주의하고, 회복과 안착 전에는 서두르지 마세요."
            lines.extend(pattern_status)
            lines.extend(pattern_opinion)
    elif scan["total"] == 0:
        lines.append("아직 분석할 종목이 없어요.")
    elif scan["failed"] == scan["total"]:
        lines.extend(["", "현재 가격을 불러오지 못했어요.", "잠시 후 다시 요청해 주세요."])
    else:
        lines.append("지금은 추천할 종목이 없어요. 잠시 후 다시 확인해 주세요.")
    if scan["results"]:
        lines.extend(["", "────────────", "매도: 기준 가격대를 회복하고 안착한 뒤, 각 종목의 저항선에서 나누어 수익실현할지 살펴보세요.",
                      "종목 버튼으로 차트와 상세 의견을 확인하세요."])
    if scan["failed"]:
        lines.append(f"일부 종목({scan['failed']}개)은 시세를 확인하지 못했어요.")
    lines.extend([f"조회 {scan['checked_at']} KST",
                  "※ 예상 수익률은 비용 제외 가정이며, 실제 손실이 날 수 있어요."])
    return "\n".join(lines)


def recommendation_pages(scan, max_chars=1000):
    """One long bubble per page; never split or discard a stock's block."""
    if not scan["results"]:
        return [(recommendation_text(scan), [])]
    groups, current, start = [], [], 0
    for stock in scan["results"]:
        proposed = current+[stock]
        if current and len(recommendation_text(scan, proposed, start, " · 999/999")) > max_chars:
            groups.append(current)
            start += len(current)
            current = [stock]
        else:
            current = proposed
    groups.append(current)
    pages, start = [], 0
    for i, group in enumerate(groups, 1):
        label = f" · {i}/{len(groups)}" if len(groups) > 1 else ""
        text = recommendation_text(scan, group, start, label)
        if len(text) > max_chars:
            raise ValueError("A single recommendation block exceeds Kakao's text limit")
        pages.append((text, group))
        start += len(group)
    return pages
