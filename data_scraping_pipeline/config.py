"""
Data Scraping Pipeline Configuration
Settings for scraping, indexing, and MongoDB write operations.
"""
import os
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # MongoDB Atlas Vector Search (WRITE OPERATIONS)
    MONGODB_URI: Optional[str] = None
    MONGODB_DB_NAME: str = "webosmotic_chatbot"
    MONGODB_COLLECTION_NAME: str = "website_documents"
    MONGODB_INDEX_NAME: str = "vector_index"

    # Embedding (for document embedding during indexing)
    VOYAGE_API_KEY: Optional[str] = None
    VOYAGE_MODELS: dict[str, str] = {"embedding": "voyage-3-large", "reranker": "rerank-2"}

    # Data pipeline configuration
    MEMORY_THRESHOLD: int = 70
    MAX_SESSION_PERMIT: int = 4
    BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
    SITEMAPS_DIR: str = os.path.join(BASE_DIR, "sitemaps")
    PAGE_CONTENTS_DIR: str = os.path.join(BASE_DIR, "page_contents")
    USE_BLOGS: bool = False

    # Logging configuration
    LOG_LEVEL: str = "INFO"

    # Environment
    ENVIRONMENT: str = "development"

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache()
def get_settings():
    """Load data scraping pipeline settings from .env file."""
    settings = Settings()
    
    if settings.ENVIRONMENT.lower() == "production":
        settings.LOG_LEVEL = "INFO"
    else:
        settings.LOG_LEVEL = "DEBUG"
    
    return settings


settings = get_settings()
