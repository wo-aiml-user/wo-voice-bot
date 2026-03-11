"""
RAG Indexer Module for Data Scraping Pipeline

This module handles the indexing of scraped content into the MongoDB vector store.
It reads the scraped JSON files from page_contents/ directory, chunks the content,
generates embeddings, and stores them in the vector store.
"""
import os
import json
from loguru import logger
from datetime import datetime
from typing import Dict, Any, Optional
from app.data_scraping_pipeline.config import settings
from app.data_scraping_pipeline.indexing.chunking import process_markdown_documents
from app.data_scraping_pipeline.indexing.vector_store import (
    connect_to_mongodb,
    disconnect_from_mongodb,
    ensure_collection, 
    empty_collection, 
    get_vector_store, 
    release_collection, 
    is_collection_empty
)


def get_latest_pagecontent_file(page_contents_dir: str) -> Optional[str]:
    """
    Get the path to the most recent page content JSON file.
    
    Args:
        page_contents_dir: Directory containing page content JSON files
        
    Returns:
        Path to the latest file, or None if no files exist
    """
    try:
        files = [f for f in os.listdir(page_contents_dir) if f.endswith('.json')]
        if not files:
            return None
            
        # Parse dates and sort
        dated_files = []
        for f in files:
            try:
                date = datetime.strptime(f.replace('.json', ''), '%Y-%m-%d')
                dated_files.append((date, os.path.join(page_contents_dir, f)))
            except ValueError:
                continue
                
        if not dated_files:
            return None
            
        dated_files.sort(key=lambda x: x[0], reverse=True)
        return dated_files[0][1]
        
    except Exception as e:
        logger.error(f"Error getting latest page content file: {e}")
        return None


def load_page_contents(file_path: str) -> Dict[str, str]:
    """
    Load page contents from a JSON file.
    
    Args:
        file_path: Path to the JSON file
        
    Returns:
        Dictionary mapping URLs to their content
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                logger.warning(f"The file {file_path} is empty.")
                return {}
            return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {file_path}: {str(e)}")
        return {}
    except Exception as e:
        logger.error(f"Error loading page contents: {str(e)}")
        return {}


def index_documents(
    data: Dict[str, str],
    min_size: int = 1000,
    max_size: int = 1100,
    overlap: int = 200
) -> Dict[str, Any]:
    """
    Index documents into the vector store.
    
    Args:
        data: Dictionary mapping URLs to their content
        min_size: Minimum chunk size
        max_size: Maximum chunk size
        overlap: Overlap between chunks
        
    Returns:
        Dictionary with indexing results
    """
    result = {
        "success": False,
        "message": "",
        "documents_count": 0,
        "error": None
    }
    
    try:
        if not data:
            result["message"] = "No data to index"
            result["success"] = True
            return result
            
        # Ensure collection exists
        ensure_collection()
        
        # Process documents
        documents = process_markdown_documents(
            json_input=data,
            min_size=min_size,
            max_size=max_size,
            overlap=overlap
        )
        
        if not documents:
            result["message"] = "No documents generated after processing"
            result["success"] = True
            return result
        
        # Check if collection is empty
        if not is_collection_empty():
            logger.info("Collection is not empty. Emptying specific URLs before adding new documents.")
            
            for url in data.keys():
                logger.info(f"Removing existing documents for URL: {url}")
                empty_collection(webpage_url=url)
        else:
            logger.info("Collection is empty. Skipping emptying step and adding all documents directly.")
        
        # Add documents to vector store
        logger.info("Adding all the documents to vector store.....")
        vector_store = get_vector_store()
        vector_store.add_documents(documents)
        
        result["documents_count"] = len(documents)
        result["message"] = f"Successfully indexed {len(documents)} documents"
        result["success"] = True
        logger.info(f"Added {len(documents)} documents to vector store")
        
        # Release collection
        release_collection()
        
    except Exception as e:
        result["message"] = f"Indexing failed: {str(e)}"
        result["error"] = str(e)
        logger.error(f"Error indexing documents: {e}", exc_info=True)
        
    return result


def run_indexer(page_contents_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Run the RAG indexer to process the latest scraped content.
    
    Args:
        page_contents_dir: Directory containing page content JSON files
        
    Returns:
        Dictionary with indexing results
    """
    if page_contents_dir is None:
        page_contents_dir = settings.PAGE_CONTENTS_DIR
        
    result = {
        "success": False,
        "message": "",
        "file_path": "",
        "documents_count": 0,
        "error": None
    }
    
    try:
        # Get latest page content file
        latest_file = get_latest_pagecontent_file(page_contents_dir)
        
        if not latest_file:
            result["message"] = f"No page content files found in {page_contents_dir}"
            logger.warning(result["message"])
            return result
            
        result["file_path"] = latest_file
        logger.info(f"Processing page contents from: {latest_file}")
        
        # Load page contents
        data = load_page_contents(latest_file)
        
        if not data:
            result["message"] = "No content to index"
            result["success"] = True
            logger.info(result["message"])
            return result
        
        # Index documents
        index_result = index_documents(data)
        
        result["success"] = index_result["success"]
        result["message"] = index_result["message"]
        result["documents_count"] = index_result["documents_count"]
        result["error"] = index_result.get("error")
        
        if is_collection_empty():
            logger.warning("Vector store is empty after indexing")
            
    except Exception as e:
        result["message"] = f"Indexer failed: {str(e)}"
        result["error"] = str(e)
        logger.error(f"Error in run_indexer: {e}", exc_info=True)
        
    return result


if __name__ == "__main__":
    print("🔌 Connecting to MongoDB Atlas...")
    try:
        connect_to_mongodb()
        print("✅ Connected to MongoDB Atlas successfully!")
        
        print("🚀 Starting RAG indexer...")
        result = run_indexer()
        
        if result["success"]:
            print(f"✅ Indexing completed: {result['message']}")
        else:
            print(f"❌ Indexing failed: {result['message']}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        print("🔌 Disconnecting from MongoDB...")
        disconnect_from_mongodb()
        print("✅ Disconnected!")
