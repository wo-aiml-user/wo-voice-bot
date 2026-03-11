"""
MongoDB Atlas Vector Search - Chat Module (READ ONLY)
Simplified version for RAG chat retrieval operations only.
"""
from loguru import logger
from typing import Optional
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from pymongo.operations import SearchIndexModel
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


async def connect_to_mongodb() -> bool:
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


async def disconnect_from_mongodb() -> bool:
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


async def is_connected() -> bool:
    """Check if connected to MongoDB."""
    global _mongo_client
    
    if _mongo_client is None:
        return False
    
    try:
        _mongo_client.admin.command('ping')
        return True
    except Exception:
        return False


async def ensure_connected():
    """Ensure connection to MongoDB exists."""
    if not await is_connected():
        raise MongoDBConnectionError("Not connected to MongoDB. Call connect_to_mongodb first.")


async def ensure_collection_and_index(collection_name: str = None):
    """Ensure the target collection and its vector search index exist."""
    await ensure_connected()
    col_name = collection_name or settings.MONGODB_COLLECTION_NAME
    db = _mongo_client[settings.MONGODB_DB_NAME]
    
    # 1. Create collection if it doesn't exist
    if col_name not in db.list_collection_names():
        logger.info(f"[MongoDB] Collection '{col_name}' does not exist. Creating it...")
        db.create_collection(col_name)
    
    collection = db[col_name]
    index_name = settings.MONGODB_INDEX_NAME
    
    # 2. Check and create vector search index if it doesn't exist
    try:
        # PyMongo >= 4.7 supports list_search_indexes()
        existing_indexes = list(collection.list_search_indexes())
        index_names = [idx.get("name") for idx in existing_indexes]
        
        if index_name not in index_names:
            logger.info(f"[MongoDB] Vector search index '{index_name}' missing. Creating it...")
            search_index_model = SearchIndexModel(
                definition={
                    "fields": [
                        {
                            "type": "vector",
                            "numDimensions": 1024,  # Default matching VoyageAI 1024
                            "path": "embedding",
                            "similarity": "cosine"
                        }
                    ]
                },
                name=index_name,
                type="vectorSearch"
            )
            # Create the index (Atlas specific, may take a few minutes to be ready)
            collection.create_search_index(model=search_index_model)
            logger.info(f"[MongoDB] Vector search index '{index_name}' creation initiated.")
    except OperationFailure as e:
        logger.warning(f"[MongoDB] Could not verify/create search index (might not be running on Atlas or lacking permissions): {e}")
    except Exception as e:
        logger.warning(f"[MongoDB] Error checking search index: {e}")


async def get_collection():
    """Get the MongoDB collection for documents."""
    await ensure_collection_and_index()
    db = _mongo_client[settings.MONGODB_DB_NAME]
    return db[settings.MONGODB_COLLECTION_NAME]


async def collection_in_db(collection_name: str = None) -> bool:
    """
    Checks if the collection exists in the database.
    
    Args:
        collection_name (str, optional): Name of the collection to check. 
                                       Defaults to settings.MONGODB_COLLECTION_NAME.
                                       
    Returns:
        bool: True if collection exists, False otherwise.
    """
    try:
        await ensure_connected()
        coll_name = collection_name or settings.MONGODB_COLLECTION_NAME
        db = _mongo_client[settings.MONGODB_DB_NAME]
        return coll_name in db.list_collection_names()
    except Exception as e:
        logger.error(f"Error checking if collection exists: {str(e)}")
        return False


async def get_vector_store(collection_name: str = None, embedding_model=None) -> MongoDBAtlasVectorSearch:
    """
    Creates a LangChain MongoDB Atlas Vector Search store for retrieval.

    Args:
        collection_name (str): The name of the collection (optional).
        embedding_model: The embedding model to use.

    Returns:
        MongoDBAtlasVectorSearch: LangChain MongoDBAtlasVectorSearch instance.
    """
    try:
        await ensure_collection_and_index(collection_name)
        
        coll_name = collection_name or settings.MONGODB_COLLECTION_NAME
            
        if embedding_model is None:
            embedding_model = CustomVoyageAIEmbeddings(
                model=settings.VOYAGE_MODELS['embedding'],
                api_key=settings.VOYAGE_API_KEY,
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