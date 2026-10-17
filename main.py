from fastapi import FastAPI, Request

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok", "message": "Kakao Bot Server is running"}

@app.post("/api/chat")
async def chat_handler(request: Request):
    try:
        body = await request.json()
        user_message = body.get("userRequest", {}).get("utterance", "")
    except Exception:
        user_message = ""
    
    reply_text = f"안녕하세요! 보내주신 메시지: '{user_message}'\n파이썬 무료 서버에서 정상 응답했습니다."
    
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