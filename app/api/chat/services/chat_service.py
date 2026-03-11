"""
Simplified chat service for Gemini RAG.
"""
from loguru import logger
from typing import Dict
from app.config import Settings
from app.api.chat.models.chat_model import ChatRequest
from app.RAG import rag_chain
from app.utils.response_formatter import format_rag_response


async def get_chat_response(request: ChatRequest, settings: Settings) -> Dict:
    """
    Generate chat response using RAG with retrieval + generation.

    Args:
        request: Chat request with user query
        settings: Application settings

    Returns:
        Chat response with answer and token usage
    """
    logger.info("[CHAT_SERVICE] Start processing request")
    logger.info(f"[CHAT_SERVICE] Query={request.user_query}")

    try:
        collection_name = settings.MONGODB_COLLECTION_NAME
        logger.info(f"[CHAT_SERVICE] Using collection={collection_name}")

        rag_response = await rag_chain.execute_rag_chain(
            request=request,
            collection_name=collection_name,
            settings=settings
        )
        logger.info("[CHAT_SERVICE] RAG chain complete")

        if "response" in rag_response:
            rag_response["answer"] = rag_response.pop("response")

        logger.info(f"[CHAT_SERVICE] Formatter input keys={list(rag_response.keys())}")
        logger.info(f"[CHAT_SERVICE] Context size={len(rag_response.get('context', []))}")
        logger.info(f"[CHAT_SERVICE] Tool names={rag_response.get('tool_names', [])}")

        formatted_response = await format_rag_response(
            response=rag_response,
            user_query=request.user_query
        )
        logger.info("[CHAT_SERVICE] Completed successfully")
        return formatted_response
    except Exception as e:
        logger.exception(f"[CHAT_SERVICE] Failed | error={str(e)}")
        raise
