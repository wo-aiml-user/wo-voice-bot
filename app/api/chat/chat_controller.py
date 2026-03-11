from fastapi import APIRouter, Request, Depends
from app.config import Settings, get_settings
from app.utils.response import success_response
from app.api.chat.models.chat_model import ChatRequest
from app.api.chat.services.chat_service import get_chat_response
from loguru import logger

router = APIRouter()

@router.post("/chat", summary="Get a response from the Chat RAG")
async def handle_chat(
    req: Request,
    chat_request: ChatRequest,
    settings: Settings = Depends(get_settings)
):
    """
    Processes a user's query using the RAG pipeline with DeepSeek.
    Returns a structured response with the AI's answer and token usage.
    """
    logger.info("[CHAT_CONTROLLER] Handling chat request")
    
    result = await get_chat_response(
        request=chat_request,
        settings=settings
    )
    
    return await success_response(data=result)


