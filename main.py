from fastapi import FastAPI, Request

app = FastAPI()

# 카카오톡 서버에서 들어오는 요청을 처리하는 엔드포인트
@app.post("/api/chat")
async def chat_handler(request: Request):
    # 1. 카카오톡이 보내준 데이터 받기
    body = await request.json()
    user_message = body.get("userRequest", {}).get("utterance", "")
    
    # 2. 챗봇 답변 메시지 작성
    reply_text = f"hello! 보내주신 메시지: '{user_message}'\n파이썬 무료 서버에서 정상 응답했습니다."
    
    # 3. 카카오톡이 요구하는 규격(JSON)으로 응답
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": reply_text
                    }
                }
            ]
        }
    }