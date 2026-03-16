import re
from loguru import logger
from typing import List, Dict, Any, Set

from .json_parser import parse_json_response

async def format_rag_response(response: Dict, user_query: str) -> Dict:
    """
    Process and format the RAG response with metadata.
    """
    try:
        response_string = response.get("answer", "")
        tool_names = response.get("tool_names", [])
        context_list = response.get("context", [])
        
        logger.info(f"Processing response. Tool(s): {tool_names}")

        # Clean and parse JSON response
        cleaned = re.sub(
            r'(?is)("ai"\s*:\s*")([\s\S]*?)(?:\\n(?:-{3,}\\n|\\n)?\s*)?[^\n\\]*\bReferences:[\s\S]*?(")',
            r'\1\2\3',
            response_string
        )
        
        json_response = await parse_json_response(cleaned)
        # Determine if context was utilized based on tool usage
        is_retrieval = "retrieve_documents" in tool_names

        formatted_response = {
            "response": json_response.get("ai") or response_string,
            "tool_used": bool(tool_names),
            "tool_name": ", ".join(tool_names) if tool_names else "",
            "meta_data": [],
            "token_usage": response.get("token_usage", {})
        }

        # Handle conversation title
        if "title" in json_response:
            formatted_response["title"] = json_response["title"]

        # If no tool used, return early with empty metadata
        if not tool_names:
            return formatted_response

        # Extract references/citations
        doc_refs = json_response.get("document_references", [])
        final_indices = []

        if doc_refs:
            # LLM provided specific citations
            for ref in doc_refs:
                try:
                    idx = int(ref) - 1
                    if 0 <= idx < len(context_list):
                        final_indices.append(idx)
                except (ValueError, TypeError):
                    continue
        
        # If no explicit refs but tools were used, fallback to including all context
        if not final_indices and tool_names:
             logger.info(f"No explicit citations found for tools {tool_names}. Falling back to all context items.")
             final_indices = list(range(len(context_list)))

        if not context_list:
            return formatted_response

        seen_texts: Set[str] = set()
        meta_data: List[Dict] = []
        
        # Process unique valid indices in original order
        unique_indices = []
        for i in final_indices:
            if i not in unique_indices and 0 <= i < len(context_list):
                unique_indices.append(i)
        
        for i in unique_indices:
            context_item = context_list[i]
            meta_item = {}
            text_preview = ""
            
            # Handle Document objects (standard retrieval)
            if hasattr(context_item, 'page_content') and hasattr(context_item, 'metadata'):
                metadata = context_item.metadata
                text_preview = context_item.page_content[:100] # Slightly larger preview for duplicate check
                
                # Prioritize webpage_url as title if it exists (from scraping pipeline)
                file_name = metadata.get("file_name") or metadata.get("webpage_url") or "Unknown File"
                
                meta_item = {
                    "text": context_item.page_content,
                    "chunk_id": metadata.get("chunk_id", ""),
                    "webpage_url": metadata.get("webpage_url", "")
                }

            # Handle dictionary-based context (fallback/other tools)
            elif isinstance(context_item, dict):
                text_preview = str(context_item.get("text", ""))
                meta_item = {
                    "text": context_item.get("text", ""),
                    "chunk_id": context_item.get("chunk_id", ""),
                    "webpage_url": context_item.get("webpage_url", "")
                }
            
            if meta_item and text_preview not in seen_texts:
                seen_texts.add(text_preview)
                meta_data.append(meta_item)
        
        formatted_response["meta_data"] = meta_data
        return formatted_response

    except Exception as e:
        logger.error(f"Error in format_rag_response: {e}")
        return {
            "response": response.get("answer", ""),
            "tool_used": False,
            "tool_name": "",
            "meta_data": [],
            "token_usage": response.get("token_usage", {})
        }