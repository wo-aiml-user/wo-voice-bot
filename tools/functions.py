"""
Tool execution functions for DeepSeek function calling.
All tool implementations with proper token tracking and detailed logging.
"""
import os
import json
from typing import List, Dict, Optional, Any
from dotenv import load_dotenv
from loguru import logger
from pymongo import MongoClient
from google import genai
from google.genai import types
from app.config import settings

load_dotenv()

class Document:
    def __init__(self, page_content: str, metadata: dict):
        self.page_content = page_content
        self.metadata = metadata



def retrieve_documents(query: str, collection_name: Optional[str] = None, file_ids: Optional[List[str]] = None, top_k: int = 5) -> tuple[List[Document], Dict[str, int]]:
    """
    Retrieve documents from MongoDB Atlas Vector Search using vanilla genai and pymongo.
    """
    token_usage = {"embedding_tokens": 0, "retrieval_tokens": 0}
    
    # Connect to MongoDB
    mongo_uri = settings.MONGODB_URI
    db_name = settings.MONGODB_DB_NAME
    col_name = collection_name or settings.MONGODB_COLLECTION_NAME
    index_name = settings.MONGODB_INDEX_NAME
    
    if not mongo_uri:
        logger.error("[RAG] MONGODB_URI is not set")
        return [], token_usage
    
    try:
        client = MongoClient(mongo_uri)
        collection = client[db_name][col_name]
        
        # Get embeddings from Gemini
        genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        logger.info(f"[RAG] Generating embedding for query: {query}")
        embed_response = genai_client.models.embed_content(
            model="text-embedding-004",
            contents=query,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
            )
        )
        
        query_vector = embed_response.embeddings[0].values
        
        # Perform Vector Search query
        pipeline = [
            {
                "$vectorSearch": {
                    "index": index_name,
                    "path": "embedding", 
                    "queryVector": query_vector,
                    "numCandidates": top_k * 10,
                    "limit": top_k
                }
            },
            {
                "$project": {
                    "text": 1,
                    "file_name": 1,
                    "score": {"$meta": "vectorSearchScore"}
                }
            }
        ]
        
        logger.info(f"[RAG] Executing $vectorSearch on {db_name}.{col_name}")
        results = collection.aggregate(pipeline)
        
        documents = []
        for res in results:
            page_content = res.get("text", "")
            metadata = {
                "file_name": res.get("file_name", "Unknown"),
                "score": res.get("score", 0.0)
            }
            documents.append(Document(page_content=page_content, metadata=metadata))
            
        client.close()
        return documents, token_usage
        
    except Exception as e:
        logger.error(f"[RAG] Document retrieval failed: {e}")
        return [], token_usage

def format_documents_for_llm(documents: List[Document]) -> str:
    """Format the retrieved documents to pass to LLM as string."""
    formatted_docs = []
    for doc in documents:
        formatted_docs.append(f"FileName: {doc.metadata.get('file_name', 'Unknown')}\nContent: {doc.page_content}")
    return "\n\n".join(formatted_docs)

def execute_tool(function_name: str, function_args: Dict, collection_name: Optional[str] = None) -> tuple[str, Any, Dict[str, int]]:
    """
    Execute a tool function by name and return result with token usage.
    """
    logger.info(f"[TOOL_EXEC] Executing {function_name}")
    logger.info(f"[TOOL_EXEC] Arguments: {function_args}")
    
    token_usage = {
        "embedding_tokens": 0
    }
    
    try:
        if function_name == "retrieve_documents":
            if not collection_name:
                logger.error("[TOOL_EXEC] Collection name required for retrieval")
                return "Error: Collection name required for document retrieval", [], token_usage
            
            query = function_args.get("query", "")
            file_ids = function_args.get("file_ids")
            
            logger.info(f"[TOOL_EXEC] Retrieving documents for query: '{query}'")
            
            documents, retrieval_tokens = retrieve_documents(
                query=query,
                collection_name=collection_name,
                file_ids=file_ids
            )
            
            token_usage.update(retrieval_tokens)
            
            result = format_documents_for_llm(documents)
            logger.info(f"[TOOL_EXEC] Retrieved {len(documents)} documents | tokens={retrieval_tokens}")
            
            return result, documents, token_usage
            
        else:
            return f"Error: Unknown tool {function_name}", [], token_usage
        
    except Exception as e:
        logger.error(f"[TOOL_EXEC] Error executing {function_name}: {e}")
        return f"Error executing {function_name}: {str(e)}", [], token_usage
