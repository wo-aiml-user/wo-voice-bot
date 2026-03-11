"""
Voice Agent WebSocket Controller.
Handles WebSocket connections for real-time voice interactions.
"""
import json
import base64
import asyncio
from typing import Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from app.config import settings
from app.api.voice.services.voice_session import VoiceAgentSession


router = APIRouter()

# Store active sessions
active_sessions: Dict[str, VoiceAgentSession] = {}


@router.websocket("/ws/{session_id}")
async def websocket_voice_endpoint(
    websocket: WebSocket,
    session_id: str
):

    """
    Handle WebSocket connection for voice agent.
    
    Message Types (Client -> Server):
    - start_session: Initialize voice agent connection
    - audio_chunk: Forward audio data (base64 encoded in audio_data field)
    - end_session: Close the session
    
    Message Types (Server -> Client):
    - session_started: Session initialized successfully
    - agent_ready: Voice agent is ready
    - settings_applied: Settings configured on agent
    - speech_started: User started speaking
    - thinking: Agent is processing
    - playback_started: Audio playback beginning
    - playback_finished: Audio playback complete
    - audio_chunk: Audio data from TTS (base64 encoded)
    - transcript: User speech transcript
    - response: Agent text response
    - function_call: Agent called a function/tool
    - function_result: Result of function call
    - error: Error message
    """
    await websocket.accept()
    logger.info(f"[{session_id}] Client connected")
    
    session = VoiceAgentSession(session_id, websocket, settings)
    active_sessions[session_id] = session
    
    try:
        while True:
            message = await websocket.receive()
            
            if message.get("type") == "websocket.disconnect":
                break
                
            if "text" in message:
                data = json.loads(message["text"])
                msg_type = data.get("type")
                
                if msg_type == "start_session":
                    logger.info(f"[{session_id}] Starting voice agent session...")
                    success = await session.connect_to_agent()
                    
                    if success:
                        # Start receiving from agent in background
                        asyncio.create_task(session.receive_from_agent())
                        await session.client_ws.send_text(json.dumps({
                            "type": "session_started",
                            "session_id": session_id
                        }))
                    else:
                        await session.client_ws.send_text(json.dumps({
                            "type": "error",
                            "message": "Failed to connect to voice agent"
                        }))
                
                elif msg_type == "audio_chunk":
                    # Decode and forward audio to Deepgram Voice Agent
                    if "audio_data" in data:
                        audio_bytes = base64.b64decode(data["audio_data"])
                        await session.forward_audio_to_agent(audio_bytes)
                
                elif msg_type == "end_session":
                    logger.info(f"[{session_id}] Ending session...")
                    break
            
            elif "bytes" in message:
                # Raw binary audio - forward directly
                await session.forward_audio_to_agent(message["bytes"])
    
    except WebSocketDisconnect:
        logger.info(f"[{session_id}] Client disconnected")
    except Exception as e:
        logger.error(f"[{session_id}] WebSocket error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await session.close()
        if session_id in active_sessions:
            del active_sessions[session_id]
