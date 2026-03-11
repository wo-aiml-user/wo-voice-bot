"""
RAG chain implementation using DeepSeek with optimized single LLM call.
Handles tool calling intelligently with proper context formatting and token tracking.
"""
from typing import Dict
from app.RAG.gemini_client import GeminiClient
from app.RAG.prompt import get_voice_prompt
from app.config import Settings
from app.api.chat.models.chat_model import ChatRequest
from tools.tools_schema import retrieval_tool
from tools.functions import execute_tool
from loguru import logger
import json


async def execute_rag_chain(request: ChatRequest, collection_name: str, settings: Settings) -> Dict:
    """
    Execute RAG chain using DeepSeek with single optimized LLM call.
    
    Args:
        request: Chat request with user query
        collection_name: Milvus collection to search
        settings: Application settings
        
    Returns:
        Response with answer and token usage
    """
    logger.info(f"[RAG_CHAIN] Starting execution for collection: {collection_name}")
    logger.info(f"[RAG_CHAIN] User query: {request.user_query}")
    
    # Initialize Gemini client
    gemini = GeminiClient(
        api_key=settings.GEMINI_API_KEY,
        model=settings.GEMINI_MODEL
    )
    logger.info("[RAG_CHAIN] Gemini client initialized")
    
    # Prepare messages with system prompt
    messages = [
        {
            "role": "system",
            "content": await get_voice_prompt()
        },
        {
            "role": "user",
            "content": request.user_query
        }
    ]
    
    # Track token usage
    total_token_usage = {
        "llm_input_tokens": 0,
        "llm_output_tokens": 0,
        "embedding_tokens": 0
    }
    
    # LLM call with tools - let Gemini decide
    logger.info("[RAG_CHAIN] Making Gemini call with tools")
    response = gemini.chat_completion(
        messages=messages,
        tools=[retrieval_tool],
        tool_choice="auto",
        temperature=0.6
    )
    
    # Update token usage
    usage = gemini.get_usage(response)
    total_token_usage["llm_input_tokens"] += usage.get("prompt_tokens", 0)
    total_token_usage["llm_output_tokens"] += usage.get("completion_tokens", 0)
    logger.info(f"[RAG_CHAIN] Initial call tokens: {usage}")
    
    # Check if tool calls were made
    tool_calls = response.choices[0].message.tool_calls if response.choices[0].message.tool_calls else []
    
    # Initialize accumulated context from tool calls
    accumulated_context = []
    
    if tool_calls:
        logger.info(f"[RAG_CHAIN] Processing {len(tool_calls)} tool call(s)")
        
        # Execute tool calls and collect results
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            logger.info(f"[RAG_CHAIN] Executing tool: {function_name}")
            logger.info(f"[RAG_CHAIN] Tool arguments: {function_args}")
            
            # Execute the tool and get result, context, and token usage
            tool_result, tool_context, tool_tokens = await execute_tool(
                function_name=function_name,
                function_args=function_args,
                collection_name=collection_name
            )
            
            # Aggregate token usage from tool execution
            total_token_usage["embedding_tokens"] += tool_tokens.get("embedding_tokens", 0)
            
            logger.info(f"[RAG_CHAIN] Tool result length: {len(tool_result)} characters")
            logger.info(f"[RAG_CHAIN] Tool tokens: {tool_tokens}")
            
            # Add tool call to messages
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": function_name,
                        "arguments": tool_call.function.arguments
                    }
                }]
            })
            
            # Format context properly for retrieval tool
            if function_name == "retrieve_documents":
                formatted_context = f"\n**Retrieved Context:**\n{tool_result}\n"
                logger.info(f"[RAG_CHAIN] context:{formatted_context}")
                tool_result = formatted_context
            
            # Accumulate context documents if available
            if isinstance(tool_context, list):
                logger.debug(f"[RAG_CHAIN] Extending context with {len(tool_context)} items from {function_name}")
                accumulated_context.extend(tool_context)
            elif tool_context:
                logger.warning(f"[RAG_CHAIN] Tool context from {function_name} was not a list ({type(tool_context)}). Appending directly.")
                accumulated_context.append(tool_context)
            else:
                logger.info(f"[RAG_CHAIN] No context returned from {function_name}")
            
            # Add tool result to messages
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result
            })
        
        # Second call: Generate final answer with tool results
        logger.info("[RAG_CHAIN] Making final Gemini call with tool results")
        final_response = gemini.chat_completion(
            messages=messages,
            temperature=0.6,
            tool_choice="none"
        )
        
        final_usage = gemini.get_usage(final_response)
        total_token_usage["llm_input_tokens"] += final_usage.get("prompt_tokens", 0)
        total_token_usage["llm_output_tokens"] += final_usage.get("completion_tokens", 0)
        logger.info(f"[RAG_CHAIN] Final call tokens: {final_usage}")
        
        answer = final_response.choices[0].message.content
    else:
        # No tool calls, use direct response
        logger.info("[RAG_CHAIN] No tool calls made, using direct response")
        answer = response.choices[0].message.content
        accumulated_context = []
    
    logger.info(f"[RAG_CHAIN] Generated answer length: {len(answer)} characters")
    logger.info(f"[RAG_CHAIN] Generated answer: {answer}")
    logger.info(f"[RAG_CHAIN] Total token usage: {total_token_usage}")
    
    # Return response with context for formatter
    return {
        "response": answer,
        "token_usage": total_token_usage,
        "context": accumulated_context,
        "tool_names": [t.function.name for t in tool_calls] if tool_calls else []
    }
