import re
from loguru import logger
from typing import List, Dict, Any, Set

from .json_parser import parse_json_response


def format_page_number(page_number: Any) -> Any:
    """
    Extract the numerical value from a page number string.
    """
    if not page_number:
        return ""
    if isinstance(page_number, int):
        return page_number
    if isinstance(page_number, str):
        if page_number.isdigit():
            return int(page_number)
        match = re.search(r'Page\s+(\d+)', page_number, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return page_number

def format_rag_response(response: Dict, user_query: str) -> Dict:
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
        
        json_response = parse_json_response(cleaned)
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

        # Extract references
        doc_refs = json_response.get("document_references", [])
        
        # If retrieval happened but no refs, we might want to be smart. 
        # But strictly following logic: extract references if present.
        
        processed_refs = []
        if doc_refs:
            try:
                processed_refs = [int(ref) for ref in doc_refs if str(ref).strip().isdigit()]
            except Exception:
                pass
        
        # If no explicit refs but tools used, check if we should fallback
        if not processed_refs and tool_names:
             # For retrieval, we did regex fallback.
             # For other tools (search, weather), if no refs, we typically want to show what was used.
             if is_retrieval:
                 # Logic already handled or we accept empty if regex failed? 
                 # Let's retry regex strictly on response string just in case
                 found_refs = re.findall(r'Context\s+(\d+)', formatted_response["response"], re.IGNORECASE)
                 if found_refs:
                     processed_refs = [int(r)-1 for r in found_refs]
             else:
                 # For search/weather, include all items by default if no specific citations
                 processed_refs = list(range(len(context_list)))

        if not context_list:
            return formatted_response

        seen_texts: Set[str] = set()
        meta_data: List[Dict] = []
        
        target_indices = processed_refs if processed_refs else []
        
        if not target_indices and not is_retrieval and context_list:
             target_indices = list(range(len(context_list)))
        
        final_indices = []
        
        if doc_refs:
             for ref in doc_refs:
                 if str(ref).strip().isdigit():
                     final_indices.append(int(ref) - 1)
        
        # Case 2: Regex Falback (Context 1 -> 0)
        elif is_retrieval:
             found_refs = re.findall(r'Context\s+(\d+)', formatted_response["response"], re.IGNORECASE)
             for r in found_refs:
                 final_indices.append(int(r) - 1)
        
        # Case 3: Non-retrieval fallback (All items)
        elif not is_retrieval and tool_names:
             final_indices = list(range(len(context_list)))
             
        # Process unique valid indices
        unique_indices = sorted(list(set([i for i in final_indices if 0 <= i < len(context_list)])))
        
        for i in unique_indices:
            context_item = context_list[i]
            meta_item = {}
            text_preview = ""
            
            if hasattr(context_item, 'page_content') and hasattr(context_item, 'metadata'):
                metadata = context_item.metadata
                text_preview = context_item.page_content[:50]
                file_name = metadata.get("file_name", "Unknown File")
                meta_item = {
                    "text": context_item.page_content,
                    "page": format_page_number(metadata.get("page_number", "")),
                    "file_id": metadata.get("file_id", ""),
                    "file_name": file_name,
                    "title": file_name,
                    "file_path": metadata.get("file_path", "")
                }

            elif isinstance(context_item, dict):
                meta_item = context_item.copy()
                # User request: title should be empty if not retrieval
                meta_item["title"] = ""
                meta_data.append(meta_item)
                continue
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