"""
MongoDB Atlas Vector Search - Chat Module (READ ONLY)
Simplified version for RAG chat retrieval operations only.
"""
from loguru import logger
from typing import Optional
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from langchain_mongodb import MongoDBAtlasVectorSearch
from app.config import settings
from app.RAG.embedding import CustomVoyageAIEmbeddings

# Global MongoDB client
_mongo_client: Optional[MongoClient] = None


class MongoDBConnectionError(Exception):
    """Custom exception for MongoDB connection issues."""
    pass


class MongoDBCollectionError(Exception):
    """Custom exception for MongoDB collection operations."""
    pass


def connect_to_mongodb() -> bool:
    """
    Connect to MongoDB Atlas.
    
    Returns:
        bool: True if connection successful.
        
    Raises:
        MongoDBConnectionError: If connection fails.
    """
    global _mongo_client
    
    try:
        if not settings.MONGODB_URI:
            raise MongoDBConnectionError("MONGODB_URI is not set in environment variables")
        
        _mongo_client = MongoClient(settings.MONGODB_URI)
        
        # Test connection by pinging the server
        _mongo_client.admin.command('ping')
        
        logger.info(f"Connected to MongoDB Atlas, database: {settings.MONGODB_DB_NAME}")
        return True
        
    except ConnectionFailure as e:
        error_msg = f"Failed to connect to MongoDB Atlas: {str(e)}"
        logger.error(error_msg)
        raise MongoDBConnectionError(error_msg) from e
    except Exception as e:
        error_msg = f"Unexpected error connecting to MongoDB: {str(e)}"
        logger.error(error_msg)
        raise MongoDBConnectionError(error_msg) from e


def disconnect_from_mongodb() -> bool:
    """
    Disconnect from MongoDB Atlas.
    
    Returns:
        bool: True if disconnection successful.
    """
    global _mongo_client
    
    try:
        if _mongo_client:
            _mongo_client.close()
            _mongo_client = None
            logger.info("Disconnected from MongoDB Atlas")
        return True
    except Exception as e:
        error_msg = f"Error disconnecting from MongoDB: {str(e)}"
        logger.error(error_msg)
        return False


def is_connected() -> bool:
    """Check if connected to MongoDB."""
    global _mongo_client
    
    if _mongo_client is None:
        return False
    
    try:
        _mongo_client.admin.command('ping')
        return True
    except Exception:
        return False


def ensure_connected():
    """Ensure connection to MongoDB exists."""
    if not is_connected():
        raise MongoDBConnectionError("Not connected to MongoDB. Call connect_to_mongodb first.")


def get_collection():
    """Get the MongoDB collection for documents."""
    ensure_connected()
    db = _mongo_client[settings.MONGODB_DB_NAME]
    return db[settings.MONGODB_COLLECTION_NAME]


def collection_in_db(collection_name: str = None) -> bool:
    """
    Checks if the collection exists in the database.
    
    Args:
        collection_name (str, optional): Name of the collection to check. 
                                       Defaults to settings.MONGODB_COLLECTION_NAME.
                                       
    Returns:
        bool: True if collection exists, False otherwise.
    """
    try:
        ensure_connected()
        coll_name = collection_name or settings.MONGODB_COLLECTION_NAME
        db = _mongo_client[settings.MONGODB_DB_NAME]
        return coll_name in db.list_collection_names()
    except Exception as e:
        logger.error(f"Error checking if collection exists: {str(e)}")
        return False


def get_vector_store(collection_name: str = None, embedding_model=None) -> MongoDBAtlasVectorSearch:
    """
    Creates a LangChain MongoDB Atlas Vector Search store for retrieval.

    Args:
        collection_name (str): The name of the collection (optional).
        embedding_model: The embedding model to use.

    Returns:
        MongoDBAtlasVectorSearch: LangChain MongoDBAtlasVectorSearch instance.
    """
    try:
        ensure_connected()
        
        coll_name = collection_name or settings.MONGODB_COLLECTION_NAME
            
        if embedding_model is None:
            embedding_model = CustomVoyageAIEmbeddings(
                model=settings.VOYAGE_MODELS['embedding'],
                api_key=settings.VOYAGE_API_KEY,  # Pass API key explicitly
                show_progress_bar=True,
                batch_size=128,
                truncation=True,
                output_dimension=1024
            )
        
        collection = _mongo_client[settings.MONGODB_DB_NAME][coll_name]
        
        vector_store = MongoDBAtlasVectorSearch(
            collection=collection,
            embedding=embedding_model,
            index_name=settings.MONGODB_INDEX_NAME,
            text_key="text",
            embedding_key="embedding"
        )
        
        doc_count = collection.count_documents({})
        logger.info(f"[MongoDB] Vector store created for collection '{coll_name}' with {doc_count} documents")
        logger.info(f"[MongoDB] Using index: '{settings.MONGODB_INDEX_NAME}', embedding dimension: 1024")
        return vector_store
            
    except Exception as e:
        if isinstance(e, (MongoDBConnectionError, MongoDBCollectionError)):
            raise
        error_msg = f"Unexpected error creating vector store: {str(e)}"
        logger.error(error_msg)
        raise MongoDBCollectionError(error_msg) from e