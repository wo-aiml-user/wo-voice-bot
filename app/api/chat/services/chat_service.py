"""
Simplified chat service for DeepSeek RAG.
"""
from loguru import logger
from typing import Dict
from app.config import Settings
from app.api.chat.models.chat_model import ChatRequest
from app.RAG import rag_chain


from app.utils.response_formatter import format_rag_response

async def get_chat_response(request: ChatRequest, settings: Settings) -> Dict:
    """
    Generate chat response using DeepSeek with tool calling.
    
    Args:
        request: Chat request with user query
        settings: Application settings
        
    Returns:
        Chat response with answer and token usage
    """
    logger.info(f"[CHAT_SERVICE] Processing chat request")
    logger.info(f"[CHAT_SERVICE] User query: {request.user_query}")
    
    # Use fixed collection name
    collection_name = "tool_calling_dev"
    
    logger.info(f"[CHAT_SERVICE] Using collection: {collection_name}")
    
    # Execute RAG chain
    rag_response = await rag_chain.execute_rag_chain(
        request=request,
        collection_name=collection_name,
        settings=settings
    )
    
    logger.info(f"[CHAT_SERVICE] RAG chain execution complete")
    
    # Adapt response for formatter (it expects 'answer' key)
    if "response" in rag_response:
        rag_response["answer"] = rag_response.pop("response")
        
    logger.info(f"[CHAT_SERVICE] Keys for formatter: {list(rag_response.keys())}")
    logger.info(f"[CHAT_SERVICE] Context size: {len(rag_response.get('context', []))}")
    logger.info(f"[CHAT_SERVICE] Tool names: {rag_response.get('tool_names', [])}")
    
    # Format and clean the response
    formatted_response = format_rag_response(
        response=rag_response,
        user_query=request.user_query
    )
    
    logger.info(f"[CHAT_SERVICE] Response generated and formatted successfully")
    return formatted_response