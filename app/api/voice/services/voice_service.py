"""
Voice Agent service for building Deepgram Voice Agent configuration.
Uses existing prompt and function schemas from the application.
"""
from typing import Dict, List
from loguru import logger
from app.config import Settings
from tools.tools_schema import retrieval_tool
from app.RAG.prompt import get_voice_prompt

async def get_function_definitions() -> List[Dict]:
    """
    Return Deepgram-compatible function definitions.
    retrieval_tool is in Deepgram flat format (name, description, parameters).
    """
    functions = []
    for tool in [retrieval_tool]:
        if not isinstance(tool, dict):
            logger.warning(f"[VOICE_SERVICE] Skipping invalid function schema (non-object): {tool}")
            continue

        # Keep only keys documented by Deepgram for function definitions.
        sanitized = {
            "name": tool.get("name"),
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters"),
        }
        if tool.get("endpoint"):
            sanitized["endpoint"] = tool["endpoint"]

        if not sanitized["name"] or not sanitized["parameters"]:
            logger.warning(f"[VOICE_SERVICE] Skipping invalid function schema: {tool}")
            continue

        functions.append(sanitized)

    logger.info(
        f"[VOICE_SERVICE] Function definitions prepared | count={len(functions)} "
        f"names={[f.get('name') for f in functions]} "
        f"server_side={[bool(f.get('endpoint')) for f in functions]}"
    )
    return functions


async def get_voice_agent_settings(settings: Settings) -> Dict:
    """
    Configure Deepgram Voice Agent with Gemini as custom LLM.
    Uses the existing prompt and function schema from the application.
    
    Args:
        settings: Application settings containing API keys
        
    Returns:
        Voice Agent settings dictionary for Deepgram API
    """
    logger.info("[VOICE_SERVICE] Building voice agent settings")
    
    # Get function definitions in Deepgram format
    function_definitions = await get_function_definitions()
    logger.info(f"[VOICE_SERVICE] Loaded {function_definitions} function definitions")
    
    # Get voice-optimized prompt
    voice_prompt = await get_voice_prompt()
    logger.info("[VOICE_SERVICE] Loaded voice-optimized prompt")

    # Use model name from settings directly
    model_name = settings.GEMINI_MODEL

    return {
        "type": "Settings",
        "audio": {
            "input": {
                "encoding": "linear16",
                "sample_rate": 16000
            },
            "output": {
                "encoding": "linear16",
                "sample_rate": 24000,
                "container": "none"
            }
        },
        "agent": {
            "language": "en",
            "listen": {
                "provider": {
                    "type": "deepgram",
                    "model": "nova-3"
                }
            },
            "think": {
                "provider": {
                    "type": "google"
                },
                "endpoint": {
                    "url": f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:streamGenerateContent?alt=sse",
                    "headers": {
                        "x-goog-api-key": settings.GEMINI_API_KEY
                    }
                },
                "prompt": voice_prompt,
                "functions": function_definitions
            },
            "speak": {
                "provider": {
                    "type": "deepgram",
                    "model": "aura-2-thalia-en"
                }
            },
            "greeting": "Hello! How can I help you today?"
        }
    }

