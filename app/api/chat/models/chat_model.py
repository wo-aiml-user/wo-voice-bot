from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional, Dict, Any, Self

class ChatMessage(BaseModel):
    """
    Represents a single message in the chat history.
    """
    role: str = Field(..., description="The role of the message sender (e.g., 'USER' or 'AI').")
    text: str = Field(..., description="The content of the message.")

    @field_validator('role')
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        """Ensures the role is one of the expected values."""
        if v.upper() not in ["USER", "AI"]:
            raise ValueError("Role must be 'USER' or 'AI'")
        return v.upper()

class ChatRequest(BaseModel):
    """
    Defines the structure for a chat request.
    """
    user_query: str = Field(..., description="The user's question or message.", min_length=1)
    file_ids: Optional[List[str]] = Field(None, description="A list of specific file IDs to search within.")

    @field_validator('user_query')
    @classmethod
    def user_query_cannot_be_empty(cls, v: str) -> str:
        """Ensures the user_query is not just whitespace."""
        if not v.strip():
            raise ValueError("user_query cannot be empty or contain only whitespace.")
        return v

class MetaData(BaseModel):
    """
    Defines the structure for metadata associated with a chat response.
    """
    text: str
    page_number: Any
    file_id: str
    file_name: str
    file_path: str


class ChatResponse(BaseModel):
    """
    Defines the structure for a chat response.
    """
    response: str
    token_usage: Dict[str, int]