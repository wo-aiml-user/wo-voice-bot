"""
RAG chain implementation for Gemini with explicit retrieval + generation flow.
"""
from typing import Dict, Any, List
from loguru import logger

from app.RAG.gemini_client import GeminiClient
from app.RAG.prompt import get_voice_prompt
from app.config import Settings
from app.api.chat.models.chat_model import ChatRequest
from tools.functions import execute_tool


async def execute_rag_chain(request: ChatRequest, collection_name: str, settings: Settings) -> Dict[str, Any]:
    """
    Execute RAG chain with explicit retrieval followed by Gemini generation.

    Args:
        request: Chat request with user query
        collection_name: Collection to search
        settings: Application settings

    Returns:
        Response payload with answer, token usage, context, and tool names
    """
    logger.info(f"[RAG_CHAIN] Start | collection={collection_name} query={request.user_query}")

    total_token_usage = {
        "llm_input_tokens": 0,
        "llm_output_tokens": 0,
        "embedding_tokens": 0,
    }

    try:
        # Step 1: Retrieve relevant context
        logger.info("[RAG_CHAIN] Step 1/3 | Retrieving context")
        tool_result, tool_context, tool_tokens = await execute_tool(
            function_name="retrieve_documents",
            function_args={"query": request.user_query},
            collection_name=collection_name,
        )

        total_token_usage["embedding_tokens"] += tool_tokens.get("embedding_tokens", 0)

        context_items: List[Any] = []
        if isinstance(tool_context, list):
            context_items = tool_context
        elif tool_context:
            context_items = [tool_context]

        has_context = bool(tool_result and tool_result.strip() and not tool_result.startswith("Error:"))
        tool_names = ["retrieve_documents"] if has_context else []

        logger.info(
            f"[RAG_CHAIN] Retrieval complete | has_context={has_context} context_items={len(context_items)} "
            f"embedding_tokens={total_token_usage['embedding_tokens']}"
        )

        # Step 2: Build prompt/messages
        logger.info("[RAG_CHAIN] Step 2/3 | Building Gemini input messages")
        system_prompt = await get_voice_prompt()

        if has_context:
            user_content = (
                f"User Query:\n{request.user_query}\n\n"
                f"Retrieved Context:\n{tool_result}\n\n"
                "Answer using the retrieved context. If context is insufficient, state that clearly."
            )
        else:
            user_content = request.user_query
            logger.warning("[RAG_CHAIN] No retrieved context available. Falling back to query-only generation")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        logger.info(f"[RAG_CHAIN] Messages ready | count={len(messages)}")

        # Step 3: Generate answer
        logger.info(f"[RAG_CHAIN] Step 3/3 | Calling Gemini model={settings.GEMINI_MODEL}")
        gemini = GeminiClient(api_key=settings.GEMINI_API_KEY, model=settings.GEMINI_MODEL)
        response = gemini.chat_completion(messages=messages, temperature=0.6)

        usage = gemini.get_usage(response)
        total_token_usage["llm_input_tokens"] += usage.get("prompt_tokens", 0)
        total_token_usage["llm_output_tokens"] += usage.get("completion_tokens", 0)

        answer = response.choices[0].message.content if response.choices else ""
        if not answer:
            answer = "I could not generate a response at this time."
            logger.warning("[RAG_CHAIN] Gemini returned empty content; using fallback answer")

        logger.info(
            f"[RAG_CHAIN] Generation complete | answer_chars={len(answer)} llm_usage={usage} "
            f"token_usage={total_token_usage}"
        )

        return {
            "response": answer,
            "token_usage": total_token_usage,
            "context": context_items,
            "tool_names": tool_names,
        }
    except Exception as e:
        logger.exception(f"[RAG_CHAIN] Execution failed | error={str(e)}")
        raise
