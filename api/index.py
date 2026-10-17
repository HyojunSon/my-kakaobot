from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "message": "Vercel Fast Server is running"}

@app.post("/api/chat")
async def chat_handler(request: Request):
    try:
        body = await request.json()
        print("--- KAKAO REQUEST BODY ---")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        
        user_message = body.get("userRequest", {}).get("utterance", "")
    except Exception as e:
        print(f"Error parsing json: {e}")
        user_message = ""
    
    reply_text = f"안녕하세요! 보내주신 메시지: '{user_message}'\nVercel 서버에서 초고속으로 응답했습니다."
    
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