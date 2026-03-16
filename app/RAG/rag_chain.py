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
        # Step 1: Initial call to evaluate intent and potentially call tools
        from tools.tools_schema import retrieval_tool
        
        logger.info("[RAG_CHAIN] Step 1 | Building Gemini input messages")
        system_prompt = await get_voice_prompt()
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.user_query},
        ]
        
        logger.info(f"[RAG_CHAIN] Calling Gemini model={settings.GEMINI_MODEL} to evaluate query")
        gemini = GeminiClient(api_key=settings.GEMINI_API_KEY, model=settings.GEMINI_MODEL)
        response = gemini.chat_completion(
            messages=messages, 
            temperature=0.6,
            tools=[retrieval_tool]
        )
        
        usage = gemini.get_usage(response)
        total_token_usage["llm_input_tokens"] += usage.get("prompt_tokens", 0)
        total_token_usage["llm_output_tokens"] += usage.get("completion_tokens", 0)
        
        message = response.choices[0].message if response.choices else None
        answer = ""
        context_items: List[Any] = []
        tool_names = []
        
        # Step 2: Handle function call if requested
        if message and getattr(message, "function_call", None):
            func_name = message.function_call.name
            func_args_str = message.function_call.arguments
            
            logger.info(f"[RAG_CHAIN] Step 2 | Model requested tool execution: {func_name}")
            import json
            try:
                func_args = json.loads(func_args_str)
            except json.JSONDecodeError:
                func_args = {}
                
            tool_result, tool_context, tool_tokens = await execute_tool(
                function_name=func_name,
                function_args=func_args,
                collection_name=collection_name,
            )
            
            total_token_usage["embedding_tokens"] += tool_tokens.get("embedding_tokens", 0)
            
            if isinstance(tool_context, list):
                context_items = tool_context
            elif tool_context:
                context_items = [tool_context]
                
            has_context = bool(tool_result and tool_result.strip() and not tool_result.startswith("Error:"))
            if has_context:
                tool_names.append(func_name)
                
            # Append assistant message with function call
            messages.append({
                "role": "assistant",
                "content": message.content,
                "function_call": {"name": func_name, "arguments": func_args_str}
            })
            
            # Append tool response
            messages.append({
                "role": "tool",
                "name": func_name,
                "content": tool_result
            })
            
            logger.info(f"[RAG_CHAIN] Step 3 | Calling Gemini model={settings.GEMINI_MODEL} with tool result")
            response = gemini.chat_completion(
                messages=messages, 
                temperature=0.6
            )
            
            usage = gemini.get_usage(response)
            total_token_usage["llm_input_tokens"] += usage.get("prompt_tokens", 0)
            total_token_usage["llm_output_tokens"] += usage.get("completion_tokens", 0)
            
            answer = response.choices[0].message.content if response.choices else ""
        else:
            logger.info("[RAG_CHAIN] Step 2 | Model responded directly without calling a tool")
            answer = message.content if message else ""

        if not answer:
            answer = "I could not generate a response at this time."
            logger.warning("[RAG_CHAIN] Gemini returned empty content; using fallback answer")

        logger.info(
            f"[RAG_CHAIN] Generation complete | answer_chars={len(answer)} "
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
