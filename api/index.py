import logging
import os
import re
import secrets
from time import perf_counter
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from urllib.parse import urlparse
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from api.chart_service import load_snapshot, resolve_stock, render_chart
from api.chart_analysis import analyze_chart
from api.message_layout import chart_bubbles

app = FastAPI()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@app.middleware("http")
async def log_request_time(request: Request, call_next):
    started = perf_counter()
    response = await call_next(request)
    elapsed = (perf_counter()-started)*1000
    response.headers["Server-Timing"] = f"app;dur={elapsed:.1f}"
    logger.info("request_timing path=%s status=%d elapsed_ms=%.1f", request.url.path, response.status_code, elapsed)
    return response

def text_response(text):
    return {"version": "2.0", "template": {"outputs": [{"simpleText": {"text": text}}]}}


def recommendation_response(scan, page=1):
    from api.recommendations import recommendation_pages
    chunks = recommendation_pages(scan)
    pages = len(chunks)
    page = min(max(page, 1), pages)
    text, stocks = chunks[page-1]
    result = {"version": "2.0", "template": {"outputs": [
        {"simpleText": {"text": text}}
    ]}}
    if scan["results"]:
        result["template"]["quickReplies"] = [
            {"label": stock["name"][:20], "action": "message", "messageText": "/차트 " + stock["code"]}
            for stock in stocks[:8]
        ]
    if page < pages:
        result["template"].setdefault("quickReplies", []).append({
            "label": "추천 이어보기", "action": "message", "messageText": f"/종목추천 {page+1}"})
    return result


def send_recommendations(callback_url, snapshot, page=1):
    import requests
    from api.recommendations import scan_recommendations
    try:
        response = recommendation_response(scan_recommendations(snapshot), page)
    except Exception:
        logger.exception("Recommendation background scan failed")
        response = text_response("종목추천 데이터를 조회하지 못했습니다. 잠시 후 다시 요청해 주세요.")
    post_callback(callback_url, response)


def post_callback(callback_url, response):
    import requests
    try:
        result = requests.post(callback_url, json=response, timeout=(3, 10), allow_redirects=False)
        result.raise_for_status()
        if result.json().get("status") not in {None, "SUCCESS"}:
            logger.error("Recommendation callback rejected")
    except Exception:
        # Do not log callback URLs: they contain one-use credentials.
        logger.error("Recommendation callback delivery failed")


def valid_callback(url):
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return (parsed.scheme == "https" and not parsed.username and not parsed.password
                and parsed.port in {None, 443} and (host == "kakao.com" or host.endswith(".kakao.com")))
    except (ValueError, TypeError):
        return False


def chart_response(stock, snapshot, image_url):
    try:
        text = analyze_chart(stock, snapshot)
    except Exception:
        logger.exception("Rule analysis failed for %s", stock["code"])
        text = "분석용 시세를 조회하지 못했습니다. 가격 제안은 보류합니다."
    chunks = chart_bubbles(text)
    return {"version": "2.0", "template": {"outputs": [
        {"simpleImage": {"imageUrl": image_url, "altText": f"{stock['name']} 최근 6개월 차트"}},
        *[{"simpleText": {"text": chunk}} for chunk in chunks]
    ]}}


def send_chart_analysis(callback_url, stock, snapshot, image_url):
    post_callback(callback_url, chart_response(stock, snapshot, image_url))

@app.get("/")
def root():
    return {"status": "ok"}

@app.post("/api/chat")
async def chat_handler(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        utterance = body["userRequest"]["utterance"]
        if not isinstance(utterance, str):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        return text_response("명령을 읽지 못했습니다. /차트 삼성전자 형식으로 입력해 주세요.")
    recommendation_match = re.fullmatch(r"/종목추천(?:\s+([1-9]\d{0,2}))?", utterance.strip())
    if recommendation_match:
        page = int(recommendation_match.group(1) or 1)
        from api.recommendations import scan_recommendations
        try:
            snapshot = load_snapshot()
            callback_url = body["userRequest"].get("callbackUrl")
            if isinstance(callback_url, str) and callback_url:
                if not valid_callback(callback_url):
                    return text_response("카카오 콜백 주소를 확인할 수 없습니다.")
                background_tasks.add_task(send_recommendations, callback_url, snapshot, page)
                return {"version": "2.0", "useCallback": True}
            scan = await run_in_threadpool(scan_recommendations, snapshot)
            return recommendation_response(scan, page)
        except Exception:
            logger.exception("Recommendation scan failed")
            return text_response("종목추천 데이터를 조회하지 못했습니다. 잠시 후 다시 요청해 주세요.")
    match = re.fullmatch(r"/차트\s+(.+?)\s*", utterance.strip())
    if not match:
        return text_response("사용법: /차트 종목명 또는 /종목추천\n예: /차트 이뮨온시아")
    try:
        snapshot = load_snapshot()
        stock = resolve_stock(match.group(1), snapshot)
    except (OSError, ValueError):
        logger.exception("Snapshot unavailable")
        return text_response("HTS 데이터가 준비되지 않았습니다. 관리자에게 동기화를 요청해 주세요.")
    if stock is None:
        return text_response("등록된 정확한 종목명 또는 6자리 종목코드를 입력해 주세요.")
    base = os.environ.get("PUBLIC_BASE_URL", str(request.base_url)).rstrip("/")
    image_url = f"{base}/api/chart/{stock['code']}.png?request={secrets.token_hex(12)}"
    callback_url = body["userRequest"].get("callbackUrl")
    if isinstance(callback_url, str) and callback_url:
        if not valid_callback(callback_url):
            return text_response("카카오 콜백 주소를 확인할 수 없습니다.")
        background_tasks.add_task(send_chart_analysis, callback_url, stock, snapshot, image_url)
        return {"version": "2.0", "useCallback": True}
    return await run_in_threadpool(chart_response, stock, snapshot, image_url)

@app.get("/api/chart/{symbol}.png")
async def chart_image(symbol: str):
    if not re.fullmatch(r"(?:[0-9A-Z]{6}|KOSPI|KOSDAQ)", symbol):
        raise HTTPException(404, "Unknown symbol")
    try:
        snapshot = load_snapshot()
        stock = resolve_stock(symbol, snapshot)
        if stock is None:
            raise HTTPException(404, "Unknown symbol")
        png = await run_in_threadpool(render_chart, stock, snapshot)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Chart failed: %s", symbol)
        raise HTTPException(502, "Chart data or rendering unavailable") from None
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})
