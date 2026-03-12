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
from app.RAG.embedding import CustomVoyageAIEmbeddings
from app.config import settings
from app.RAG.vector_store import ensure_collection_and_index
import traceback
load_dotenv()

class Document:
    def __init__(self, page_content: str, metadata: dict):
        self.page_content = page_content
        self.metadata = metadata


def _preview_text(text: str, limit: int = 240) -> str:
    """Compact single-line preview for chunk logging."""
    if not text:
        return ""
    one_line = " ".join(text.split())
    return one_line[:limit] + ("..." if len(one_line) > limit else "")



async def retrieve_documents(query: str, collection_name: Optional[str] = None, file_ids: Optional[List[str]] = None, top_k: int = 12, top_n: int = 8) -> tuple[List[Document], Dict[str, int]]:
    """
    Retrieve documents from MongoDB Atlas Vector Search using Voyage AI and pymongo,
    then rerank them using Voyage AI Reranker.
    """
    token_usage = {"embedding_tokens": 0, "rerank_tokens": 0}
    
    # Connect to MongoDB
    mongo_uri = settings.MONGODB_URI
    db_name = settings.MONGODB_DB_NAME
    col_name = collection_name or settings.MONGODB_COLLECTION_NAME
    index_name = settings.MONGODB_INDEX_NAME
    
    if not mongo_uri:
        logger.error("[RAG] MONGODB_URI is not set")
    try:
        await ensure_collection_and_index(col_name)
        
        client = MongoClient(mongo_uri)
        collection = client[db_name][col_name]
        
        # Get embeddings from Voyage AI
        embedder = CustomVoyageAIEmbeddings(
            model=settings.VOYAGE_MODELS.get('embedding', 'voyage-3-large'),
            voyage_api_key=settings.VOYAGE_API_KEY,
            truncation=True,
            output_dimension=1024
        )
        
        logger.info(f"[RAG] Generating embedding for query: {query}")
        query_vector = embedder.embed_query(query)
        token_usage["embedding_tokens"] = embedder.get_total_tokens()
        
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
        
        logger.info(f"[RAG] Executing $vectorSearch on {db_name}.{col_name} (top_k={top_k})")
        results = list(collection.aggregate(pipeline))
        
        if not results:
            client.close()
            return [], token_usage

        # Prepare for reranking
        documents_to_rerank = []
        original_docs = []
        for res in results:
            text = res.get("text", "")
            documents_to_rerank.append(text)
            original_docs.append(Document(
                page_content=text,
                metadata={
                    "file_name": res.get("file_name", "Unknown"),
                    "score": res.get("score", 0.0)
                }
            ))

        logger.info(f"[RAG] Reranking {len(documents_to_rerank)} documents to top_n={top_n}")
        rerank_model = settings.VOYAGE_MODELS.get('reranker', 'rerank-2')
        rerank_result = embedder.rerank(
            query=query,
            documents=documents_to_rerank,
            model=rerank_model,
            top_k=top_n
        )
        
        token_usage["rerank_tokens"] = embedder._rerank_tokens
        
        # Build final document list based on reranker results
        final_documents = []
        for r in rerank_result.results:
            doc_idx = r.index
            doc = original_docs[doc_idx]
            # Update metadata with reranker score
            doc.metadata["rerank_score"] = r.relevance_score
            final_documents.append(doc)
            
        client.close()
        return final_documents, token_usage
        
    except Exception as e:
        logger.error(f"[RAG] Document retrieval and reranking failed: {e}")
        logger.error(traceback.format_exc())
        return [], token_usage

async def format_documents_for_llm(documents: List[Document]) -> str:
    """Format the retrieved documents to pass to LLM as string."""
    formatted_docs = []
    for doc in documents:
        formatted_docs.append(f"FileName: {doc.metadata.get('file_name', 'Unknown')}\nContent: {doc.page_content}")
    return "\n\n".join(formatted_docs)

async def execute_tool(function_name: str, function_args: Dict, collection_name: Optional[str] = None) -> tuple[str, Any, Dict[str, int]]:
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
            
            documents, retrieval_tokens = await retrieve_documents(
                query=query,
                collection_name=collection_name,
                file_ids=file_ids
            )
            
            token_usage.update(retrieval_tokens)

            for idx, doc in enumerate(documents, start=1):
                chunk_text = doc.page_content or ""
                logger.info(
                    f"[TOOL_EXEC] Chunk {idx}/{len(documents)} | "
                    f"score={doc.metadata.get('score', 0.0):.4f} | "
                    f"source={doc.metadata.get('file_name', 'Unknown')} | "
                    f"chars={len(chunk_text)}"
                )
                logger.info(f"[TOOL_EXEC] Chunk preview {idx}: {_preview_text(chunk_text)}")
            
            result = await format_documents_for_llm(documents)
            logger.info(f"[TOOL_EXEC] Retrieved {len(documents)} documents | tokens={retrieval_tokens}")
            
            return result, documents, token_usage
            
        else:
            return f"Error: Unknown tool {function_name}", [], token_usage
        
    except Exception as e:
        logger.error(f"[TOOL_EXEC] Error executing {function_name}: {e}")
        return f"Error executing {function_name}: {str(e)}", [], token_usage
