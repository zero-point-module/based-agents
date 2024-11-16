from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from src.services.warpcast_service import WarpcastService
from src.services.chatbot_service import ChatbotService

app = FastAPI()
warpcast_service = WarpcastService()
chatbot_service = ChatbotService()

@app.on_event("startup")
async def startup_event():
    warpcast_success = await warpcast_service.initialize()
    if not not warpcast_success:
        raise Exception("Failed to initialize services")

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.get("/api/warpcast/{username}")
async def get_user_casts(username: str, limit: int = 1000):
    casts = await warpcast_service.get_user_casts(username, limit)
    if "error" in casts:
        raise HTTPException(status_code=400, detail=casts["error"])
    return casts

class ChatDto(BaseModel):
    message: str
    
@app.post("/api/chat/{username}")
async def chat(request: Request, username: str, chat_dto: ChatDto):
    messages = [{"role": "user", "content": chat_dto.message}]
    response = await chatbot_service.stream(username, messages)
    if "error" in response:
        raise HTTPException(status_code=400, detail=response["error"])
    return response

