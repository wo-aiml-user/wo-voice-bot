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
class FunctionCall:
    """Represents a function call in the response."""
    name: str
    arguments: str

@dataclass
class Message:
    """Represents a message in the response."""
    content: Optional[str]
    function_call: Optional[FunctionCall] = None
    role: str = "assistant"


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
                if msg.get("function_call"):
                    fc = msg.get("function_call")
                    import json
                    args = json.loads(fc.get("arguments", "{}")) if isinstance(fc.get("arguments"), str) else fc.get("arguments", {})
                    
                    parts = []
                    if content:
                        parts.append(types.Part.from_text(text=content))
                    parts.append(types.Part.from_function_call(name=fc["name"], args=args))
                    
                    contents.append(types.Content(
                        role="model",
                        parts=parts
                    ))
                elif content:
                    contents.append(types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=content)]
                    ))
            elif role == "tool" or role == "function":
                func_name = msg.get("name", "")
                func_content = content
                if isinstance(func_content, str):
                    try:
                        import json
                        parsed_content = json.loads(func_content)
                        if isinstance(parsed_content, dict):
                            func_content = parsed_content
                    except Exception:
                        pass
                
                if not isinstance(func_content, dict):
                    func_content = {"result": func_content}

                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_function_response(name=func_name, response=func_content)]
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
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> ChatCompletionResponse:
        """
        Create a chat completion.
        Returns OpenAI-compatible response format.
        
        Args:
            messages: List of message dictionaries (OpenAI format)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            tools: List of tool schemas in dict format
            
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
                
            if tools:
                gemini_tools = []
                for tool in tools:
                    f = tool.get("function", tool)
                    func_decl = types.FunctionDeclaration(
                        name=f["name"],
                        description=f.get("description", ""),
                        parameters=f.get("parameters")
                    )
                    gemini_tools.append(types.Tool(function_declarations=[func_decl]))
                config_kwargs["tools"] = gemini_tools
            
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
        function_call = None
        
        # Extract content from response
        if response.candidates and response.candidates[0].content:
            parts = response.candidates[0].content.parts
            text_parts = []
            
            for part in parts:
                if hasattr(part, 'function_call') and part.function_call:
                    import json
                    args = part.function_call.args
                    if hasattr(args, "items"):
                        args_json = json.dumps(dict(args))
                    else:
                        args_json = json.dumps(args)
                    function_call = FunctionCall(
                        name=part.function_call.name,
                        arguments=args_json
                    )
                elif hasattr(part, 'text') and part.text:
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
            choices=[Choice(message=Message(content=content, function_call=function_call))],
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