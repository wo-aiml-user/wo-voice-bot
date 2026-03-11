"""
Pydantic models for Voice Agent configuration.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class AudioInputConfig(BaseModel):
    """Audio input configuration for STT."""
    encoding: str = Field(default="linear16", description="Audio encoding format")
    sample_rate: int = Field(default=16000, description="Audio sample rate in Hz")


class AudioOutputConfig(BaseModel):
    """Audio output configuration for TTS."""
    encoding: str = Field(default="linear16", description="Audio encoding format")
    sample_rate: int = Field(default=24000, description="Audio sample rate in Hz")
    container: str = Field(default="none", description="Audio container format")


class AudioConfig(BaseModel):
    """Combined audio configuration."""
    input: AudioInputConfig = Field(default_factory=AudioInputConfig)
    output: AudioOutputConfig = Field(default_factory=AudioOutputConfig)


class VoiceAgentConfig(BaseModel):
    """Configuration for the voice agent session."""
    language: str = Field(default="en", description="Language for the agent")
    stt_model: str = Field(default="nova-3", description="Speech-to-text model")
    tts_model: str = Field(default="aura-2-thalia-en", description="Text-to-speech model")
    llm_model: str = Field(default="deepseek-chat", description="LLM model name")
    temperature: float = Field(default=0.4, description="LLM temperature")
    greeting: Optional[str] = Field(
        default="Hello! How can I help you today?",
        description="Initial greeting message"
    )


class VoiceSessionStatus(BaseModel):
    """Status information for a voice session."""
    session_id: str
    is_active: bool = True
    audio_chunk_count: int = 0
    connected_to_agent: bool = False
