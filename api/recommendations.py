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
    skipped = 0
    for drawing in drawings:
        try:
            values = line_values(drawing, dates, latest, latest)
            if values is None or not math.isfinite(values[1]) or values[1] <= 0:
                skipped += 1
                continue
            gap = (close-values[1])/values[1]*100
            if abs(gap) <= threshold + 1e-9 and (nearest is None or abs(gap) < abs(nearest)):
                nearest = gap
        except (KeyError, ValueError, TypeError, OverflowError):
            skipped += 1
    result = None if nearest is None else {
        "code": stock["code"], "name": stock["name"], "gap": nearest,
        "date": df.index[-1].strftime("%Y-%m-%d")}
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
    lines = ["추세선 ±1% 이내 종목", f"조회 {scan['checked_at']} KST · 최신 일봉 종가 기준"]
    if scan["dates"]:
        lines.append("시세 기준일: " + " ~ ".join(dict.fromkeys([scan["dates"][0], scan["dates"][-1]])))
    if scan["results"]:
        lines.extend(f"{r['name']} ({r['code']}) {r['gap']:+.2f}%" for r in scan["results"])
    elif scan["total"] == 0:
        lines.append("저장된 추세선이 있는 종목이 없습니다.")
    elif scan["failed"] == scan["total"]:
        lines.append("시세 조회에 실패했습니다. 잠시 후 다시 요청해 주세요.")
    else:
        lines.append("조회에 성공한 종목 중 조건에 맞는 종목이 없습니다.")
    lines.append(f"대상 {scan['total']}개 · 조회 실패 {scan['failed']}개 · 계산 불가 선 {scan['skipped']}개")
    return "\n".join(lines)
