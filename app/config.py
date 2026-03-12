from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Base configuration
    APP_NAME: str = "FastAPI Project"
    DEBUG: bool = False

    # JWT configuration
    JWT_SECRET_KEY: str = "your-secret-key-here"  # Change this in production!
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Logging configuration
    LOG_LEVEL: str = "INFO"

    # CORS configuration
    CORS_ORIGINS: str = ""  # Empty by default, set to comma-separated list of domains or "*" for all
    CORS_METHODS: list = ["*"]
    CORS_HEADERS: list = ["*"]

    # MongoDB Atlas Vector Search (READ ONLY)
    MONGODB_URI: Optional[str] = None
    MONGODB_COLLECTION_NAME: str = "website_documents"
    MONGODB_INDEX_NAME: str = "vector_index"
    MONGODB_DB_NAME: str = "webosmotic_chatbot"

    # LLM configuration
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.5-flash"


    # Embedding and Reranker (for query embedding)
    VOYAGE_API_KEY: Optional[str] = None
    VOYAGE_MODELS: dict[str, str] = {"embedding": "voyage-3-large", "reranker": "rerank-2"}

    # Deepgram configuration (for voice agent)
    DEEPGRAM_API_KEY: Optional[str] = None
    VOICE_AGENT_URL: str = "wss://agent.deepgram.com/v1/agent/converse"
    
    # Environment-specific settings (for dynamic behavior)
    ENVIRONMENT: str = "development"  # Default to development

    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore"
    }


@lru_cache()
def get_settings():
    """
    Function to load settings from the `.env` file.
    """
    settings = Settings()  # Load the settings from the .env file
    
    # Adjust settings dynamically based on the environment
    if settings.ENVIRONMENT.lower() == "production":
        settings.DEBUG = False
        settings.LOG_LEVEL = "INFO"
        # Parse CORS origins from the environment string
        if settings.CORS_ORIGINS:
            # Remove quotes if present
            cors_str = settings.CORS_ORIGINS.strip('"').strip("'")
            if cors_str == "*":
                settings.CORS_ORIGINS = "[]"  # Disallow "*" in production for security
            else:
                settings.CORS_ORIGINS = ",".join([origin.strip() for origin in cors_str.split(",") if origin.strip()])
        else:
            settings.CORS_ORIGINS = ""  # No CORS origins allowed if not specified
        settings.CORS_HEADERS = [
            "Authorization",  # For JWT tokens
            "Content-Type",   # For application/json and other content types
            "Accept",         # For content negotiation
            "Origin",        # Required for CORS
            "X-Requested-With"  # For AJAX requests
        ]
    else:
        settings.DEBUG = True
        settings.LOG_LEVEL = "DEBUG"
        settings.CORS_ORIGINS = "*"  # Allow all origins for development
    
    return settings


# Create a settings instance
settings = get_settings()