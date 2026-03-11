"""
MongoDB Atlas Vector Search - Data Injection Module (WRITE OPERATIONS)
Handles database operations for indexing scraped content and creating vector search index.
"""
from loguru import logger
from typing import Optional
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from pymongo.operations import SearchIndexModel
from langchain_mongodb import MongoDBAtlasVectorSearch
from data_scraping_pipeline.config import settings
from data_scraping_pipeline.indexing.embedding import CustomVoyageAIEmbeddings

# Global MongoDB client
_mongo_client: Optional[MongoClient] = None


class MongoDBConnectionError(Exception):
    """Custom exception for MongoDB connection issues."""
    pass


class MongoDBCollectionError(Exception):
    """Custom exception for MongoDB collection operations."""
    pass


def connect_to_mongodb() -> bool:
    """Connect to MongoDB Atlas."""
    global _mongo_client
    
    try:
        if not settings.MONGODB_URI:
            raise MongoDBConnectionError("MONGODB_URI is not set in environment variables")
        
        _mongo_client = MongoClient(settings.MONGODB_URI)
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
    """Disconnect from MongoDB Atlas."""
    global _mongo_client
    
    try:
        if _mongo_client:
            _mongo_client.close()
            _mongo_client = None
            logger.info("Disconnected from MongoDB Atlas")
        return True
    except Exception as e:
        logger.error(f"Error disconnecting from MongoDB: {str(e)}")
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


def ensure_collection() -> bool:
    """Ensure the collection exists."""
    try:
        ensure_connected()
        db = _mongo_client[settings.MONGODB_DB_NAME]
        if settings.MONGODB_COLLECTION_NAME in db.list_collection_names():
            logger.info(f"Collection '{settings.MONGODB_COLLECTION_NAME}' exists")
        else:
            logger.info(f"Collection '{settings.MONGODB_COLLECTION_NAME}' does not exist. Creating it...")
            db.create_collection(settings.MONGODB_COLLECTION_NAME)
        return True
    except Exception as e:
        logger.error(f"Error ensuring collection: {str(e)}")
        raise MongoDBCollectionError(f"Error ensuring collection: {str(e)}") from e


def create_vector_search_index() -> bool:
    """
    Create a MongoDB Atlas Vector Search index if it doesn't exist.
    Should be called during data injection to ensure the index exists.
    
    Returns:
        bool: True if index exists or was created successfully.
    """
    try:
        ensure_connected()
        
        db = _mongo_client[settings.MONGODB_DB_NAME]

        # Check if collection exists
        if settings.MONGODB_COLLECTION_NAME not in db.list_collection_names():
            logger.info(f"Collection '{settings.MONGODB_COLLECTION_NAME}' does not exist. Creating it...")
            db.create_collection(settings.MONGODB_COLLECTION_NAME)

        collection = db[settings.MONGODB_COLLECTION_NAME]
        
        # Check if index already exists
        try:
            existing_indexes = list(collection.list_search_indexes())
            for index in existing_indexes:
                if index.get("name") == settings.MONGODB_INDEX_NAME:
                    logger.info(f"[MongoDB] Vector search index '{settings.MONGODB_INDEX_NAME}' already exists")
                    return True
        except Exception as e:
            logger.debug(f"[MongoDB] Could not list existing indexes: {str(e)}")
        
        # Define and create the vector search index
        index_definition = {
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": 1024,
                    "similarity": "cosine"
                },
                {
                    "type": "filter",
                    "path": "webpage_url"
                }
            ]
        }
        
        logger.info(f"[MongoDB] Creating vector search index '{settings.MONGODB_INDEX_NAME}'...")
        
        try:
            search_index_model = SearchIndexModel(
                definition=index_definition,
                name=settings.MONGODB_INDEX_NAME,
                type="vectorSearch"
            )
            
            result = collection.create_search_index(model=search_index_model)
            logger.info(f"[MongoDB] Vector search index created successfully: {result}")
            logger.info(f"[MongoDB] Note: Index may take 1-2 minutes to become active")
            return True
            
        except OperationFailure as e:
            if "already exists" in str(e).lower():
                logger.info(f"[MongoDB] Vector search index '{settings.MONGODB_INDEX_NAME}' already exists")
                return True
            raise
            
    except Exception as e:
        if isinstance(e, (MongoDBConnectionError, MongoDBCollectionError)):
            raise
        error_msg = f"Failed to create vector search index: {str(e)}"
        logger.error(error_msg)
        logger.warning("[MongoDB] Vector search index creation failed. Please create it manually.")
        return False


def get_vector_store(collection_name: str = None, embedding_model=None) -> MongoDBAtlasVectorSearch:
    """Creates a LangChain MongoDB Atlas Vector Search store for adding documents."""
    try:
        ensure_connected()
        
        coll_name = collection_name or settings.MONGODB_COLLECTION_NAME
            
        if embedding_model is None:
            embedding_model = CustomVoyageAIEmbeddings(
                model=settings.VOYAGE_MODELS['embedding'],
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
        return vector_store
            
    except Exception as e:
        if isinstance(e, (MongoDBConnectionError, MongoDBCollectionError)):
            raise
        raise MongoDBCollectionError(f"Unexpected error creating vector store: {str(e)}") from e


def empty_collection(collection_name: str = None, webpage_url: Optional[str] = None) -> int:
    """
    Delete documents from collection based on webpage_url.
    If webpage_url is None, deletes all documents.
    """
    try:
        ensure_connected()
        
        coll_name = collection_name or settings.MONGODB_COLLECTION_NAME
        collection = get_collection()
        
        if webpage_url:
            filter_query = {"webpage_url": webpage_url}
            logger.info(f"Deleting documents for webpage_url: {webpage_url}")
        else:
            filter_query = {}
            logger.info("Deleting all documents in collection")
        
        result = collection.delete_many(filter_query)
        logger.info(f"Successfully deleted {result.deleted_count} documents")
        return result.deleted_count
        
    except Exception as e:
        if isinstance(e, (MongoDBConnectionError, MongoDBCollectionError)):
            raise
        raise MongoDBCollectionError(f"Failed to empty collection: {str(e)}") from e


def is_collection_empty(collection_name: str = None) -> bool:
    """Checks if a MongoDB collection is empty."""
    try:
        ensure_connected()
        
        coll_name = collection_name or settings.MONGODB_COLLECTION_NAME
        db = _mongo_client[settings.MONGODB_DB_NAME]
        
        if coll_name not in db.list_collection_names():
            logger.warning(f"Collection '{coll_name}' does not exist.")
            return True
        
        collection = db[coll_name]
        count = collection.count_documents({})
        
        is_empty = count == 0
        if is_empty:
            logger.warning(f"Collection '{coll_name}' is empty.")
        else:
            logger.info(f"Collection '{coll_name}' contains {count} documents.")
            
        return is_empty
        
    except Exception as e:
        logger.error(f"Error checking if collection is empty: {str(e)}")
        return True


def release_collection(collection_name: str = None) -> bool:
    """No-op for MongoDB - kept for API compatibility."""
    return True
