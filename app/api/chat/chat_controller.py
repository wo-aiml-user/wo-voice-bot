from fastapi import APIRouter, Request, Depends
from app.config import Settings, get_settings
from app.utils.response import success_response
from app.api.chat.models.chat_model import ChatRequest
from app.api.chat.services.chat_service import get_chat_response
from loguru import logger

router = APIRouter()


@router.post("/", summary="Get a response from the Chat RAG")
async def handle_chat(
    req: Request,
    chat_request: ChatRequest,
    settings: Settings = Depends(get_settings)
):
    """
    Processes a user's query using the RAG pipeline with Gemini.
    Returns a structured response with the AI's answer and token usage.
    """
    user_id = getattr(req.state, "user_id", None)

    logger.info(
        f"[CHAT_CONTROLLER] Request start | path={req.url.path} method={req.method} "
        f"user_id={user_id} query_len={len(chat_request.user_query)}"
    )

    try:
        result = await get_chat_response(
            request=chat_request,
            settings=settings
        )

        logger.info(
            f"[CHAT_CONTROLLER] Request success | user_id={user_id} "
            f"response_keys={list(result.keys())}"
        )
        return await success_response(data=result)
    except Exception as e:
        logger.exception(
            f"[CHAT_CONTROLLER] Request failed | user_id={user_id} "
            f"error={str(e)}"
        )
        raise
