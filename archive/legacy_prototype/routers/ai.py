from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.ai_service import AIService

router = APIRouter(prefix="/ai", tags=["AI Integration"])
ai_service = AIService()

class PromptRequest(BaseModel):
    prompt: str

@router.post("/chat")
async def chat_with_local_model(request: PromptRequest):
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="الرجاء كتابة نص السؤال")
        
    response_text = await ai_service.generate_response(request.prompt)
    return {"status": "success", "response": response_text}
