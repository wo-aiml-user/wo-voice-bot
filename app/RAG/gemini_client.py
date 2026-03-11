"""
Gemini client wrapper using google-genai SDK.
Provides chat completions.
"""
import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from google import genai
from google.genai import types
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class Message:
    """Represents a message in the response."""
    content: Optional[str]


@dataclass
class Choice:
    """Represents a choice in the response."""
    message: Message


@dataclass
class Usage:
    """Token usage information."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class ChatCompletionResponse:
    """OpenAI-compatible response wrapper for Gemini responses."""
    choices: List[Choice]
    usage: Optional[Usage]


class GeminiClient:
    """
    Gemini client wrapper using google-genai SDK.
    Provides OpenAI-compatible interface for easy migration.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.5-flash"):
        """
        Initialize Gemini client.
        
        Args:
            api_key: Gemini API key (defaults to GEMINI_API_KEY env var)
            model: Model name to use (default: gemini-2.5-flash)
        """
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required")
        
        self.client = genai.Client(api_key=api_key)
        self.model = model
    
    def _convert_messages_to_gemini(self, messages: List[Dict[str, Any]]) -> tuple:
        """
        Convert OpenAI-format messages to Gemini format.
        
        Args:
            messages: List of OpenAI-format messages
            
        Returns:
            Tuple of (system_instruction, contents)
        """
        system_instruction = None
        contents = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                system_instruction = content
            elif role == "user":
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=content)]
                ))
            elif role == "assistant":
                if content:
                    contents.append(types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=content)]
                    ))
        
        return system_instruction, contents
    
    @retry(
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(4)
    )
    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.6,
        max_tokens: Optional[int] = None
    ) -> ChatCompletionResponse:
        """
        Create a chat completion.
        Returns OpenAI-compatible response format.
        
        Args:
            messages: List of message dictionaries (OpenAI format)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Returns:
            OpenAI-compatible ChatCompletionResponse
        """
        try:
            # Convert messages
            system_instruction, contents = self._convert_messages_to_gemini(messages)
            
            # Build config
            config_kwargs = {
                "temperature": temperature,
            }
            
            if max_tokens:
                config_kwargs["max_output_tokens"] = max_tokens
            
            if system_instruction:
                config_kwargs["system_instruction"] = system_instruction
            
            generate_config = types.GenerateContentConfig(**config_kwargs)
            
            # Make the API call
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=generate_config
            )
            
            # Convert response to OpenAI-compatible format
            return self._convert_response_to_openai_format(response)
            
        except Exception as e:
            logger.error(f"Error in Gemini chat completion: {e}")
            raise
    
    def _convert_response_to_openai_format(self, response) -> ChatCompletionResponse:
        """
        Convert Gemini response to OpenAI-compatible format.
        
        Args:
            response: Gemini GenerateContentResponse
            
        Returns:
            OpenAI-compatible ChatCompletionResponse
        """
        content = None
        
        # Extract content from response
        if response.candidates and response.candidates[0].content:
            parts = response.candidates[0].content.parts
            text_parts = []
            
            for part in parts:
                if hasattr(part, 'text') and part.text:
                    text_parts.append(part.text)
            
            if text_parts:
                content = "".join(text_parts)
        
        # Extract usage if available
        usage = None
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            usage = Usage(
                prompt_tokens=response.usage_metadata.prompt_token_count or 0,
                completion_tokens=response.usage_metadata.candidates_token_count or 0,
                total_tokens=response.usage_metadata.total_token_count or 0
            )
        
        return ChatCompletionResponse(
            choices=[Choice(message=Message(content=content))],
            usage=usage
        )
    
    def get_usage(self, response: ChatCompletionResponse) -> Dict[str, int]:
        """
        Extract token usage from response.
        
        Args:
            response: Chat completion response
            
        Returns:
            Dictionary with token usage metrics
        """
        if response.usage:
            return {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}