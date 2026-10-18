import logging
import os
import re
import secrets
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from api.chart_service import load_snapshot, resolve_stock, render_chart

app = FastAPI()
logger = logging.getLogger(__name__)

def text_response(text):
    return {"version": "2.0", "template": {"outputs": [{"simpleText": {"text": text}}]}}

@app.get("/")
def root():
    return {"status": "ok"}

@app.post("/api/chat")
async def chat_handler(request: Request):
    try:
        body = await request.json()
        utterance = body["userRequest"]["utterance"]
        if not isinstance(utterance, str):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        return text_response("명령을 읽지 못했습니다. /차트 이뮨온시아 형식으로 입력해 주세요.")
    match = re.fullmatch(r"/차트\s+(.+?)\s*", utterance.strip())
    if not match:
        return text_response("사용법: /차트 종목명 또는 /차트 6자리종목코드\n예: /차트 이뮨온시아")
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
    count = len(snapshot.get("drawings", {}).get(stock["code"], []))
    note = f"HTS 저장선 {count}개" if count else "저장된 선이 없어 캔들만 표시합니다."
    result = text_response(f"{stock['name']} ({stock['code']}) 최근 6개월 일봉\n{note}\n이미지 조회 시 제공처 최신 시세 반영 (지연 가능)")
    result["template"]["outputs"].append({"simpleImage": {"imageUrl": image_url, "altText": f"{stock['name']} 최근 6개월 차트"}})
    return result

@app.get("/api/chart/{symbol}.png")
async def chart_image(symbol: str):
    if not re.fullmatch(r"\d{6}", symbol):
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
