"""
Voice Agent Session management.
Handles WebSocket connection to Deepgram Voice Agent API.
"""
import json
import base64
import asyncio
import time
from typing import Optional
import websockets
from fastapi import WebSocket
from loguru import logger
from pymongo import MongoClient
import datetime
from app.config import Settings
from app.api.voice.services.voice_service import get_voice_agent_settings
from tools.functions import retrieve_documents
import traceback



class VoiceAgentSession:
    """Manages a session with Deepgram Voice Agent API."""
    
    def __init__(self, session_id: str, client_ws: WebSocket, settings: Settings):
        self.session_id = session_id
        self.client_ws = client_ws
        self.settings = settings
        self.mongo_client = MongoClient(self.settings.MONGODB_URI)
        self.db = self.mongo_client[self.settings.MONGODB_DB_NAME]
        self.user_data_collection = self.db["user_data"]
        self.agent_ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_active = True
        self.start_time: Optional[float] = None
        self.audio_chunk_count = 0
        self.playback_started_sent = False

    @staticmethod
    def _log_preview(value, limit: int = 600) -> str:
        """Serialize values safely and cap log size."""
        try:
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        except Exception:
            text = str(value)
        return text[:limit] + ("..." if len(text) > limit else "")

    async def _notify_client_error(self, message: str):
        """Best-effort client error propagation without breaking cleanup flow."""
        try:
            await self.client_ws.send_text(json.dumps({
                "type": "error",
                "message": message
            }))
        except Exception as e:
            logger.debug(f"[{self.session_id}] Failed to notify client error: {e}")

    def _mark_agent_closed(self):
        """Mark the Deepgram socket as inactive so audio forwarding stops cleanly."""
        self.is_active = False
        self.agent_ws = None
    
    async def connect_to_agent(self) -> bool:
        """Connect to Deepgram Voice Agent API."""
        try:
            deepgram_api_key = self.settings.DEEPGRAM_API_KEY
            if not deepgram_api_key:
                logger.error(f"[{self.session_id}] DEEPGRAM_API_KEY not configured")
                return False
            
            # Log keys securely for debugging
            logger.info(f"[{self.session_id}] Connecting to Deepgram...")
            gemini_key = self.settings.GEMINI_API_KEY
            if gemini_key:
                logger.info(f"[{self.session_id}] Gemini Key loaded")
            else:
                logger.warning(f"[{self.session_id}] Gemini Key NOT loaded")

            # Connect without ping timeout settings
            self.agent_ws = await websockets.connect(
                self.settings.VOICE_AGENT_URL,
                additional_headers={"Authorization": f"Token {deepgram_api_key}"}
            )
            logger.info(f"[{self.session_id}] Connected to Deepgram Voice Agent")
            
            # Send Settings message to configure the agent
            settings_dict = await get_voice_agent_settings(self.settings)
            function_names = [
                f.get("name", "<unknown>")
                for f in settings_dict.get("agent", {}).get("think", {}).get("functions", [])
                if isinstance(f, dict)
            ]
            logger.info(
                f"[{self.session_id}] Function-calling configured | "
                f"count={len(function_names)} names={function_names}"
            )
            await self.agent_ws.send(json.dumps(settings_dict))
            logger.info(f"[{self.session_id}] Sent Settings to Voice Agent")
            
            return True
        except Exception as e:
            logger.error(f"[{self.session_id}] Failed to connect to Voice Agent: {e}")
            return False

    
    async def forward_audio_to_agent(self, audio_data: bytes):
        """Forward audio from client to Deepgram Voice Agent."""
        if not self.agent_ws:
            return

        try:
            await self.agent_ws.send(audio_data)
        except websockets.exceptions.ConnectionClosed as e:
            self._mark_agent_closed()
            reason = (e.reason or "").strip() or "no reason provided"
            if e.code == 1005:
                reason = "no status received from agent"
            logger.warning(
                f"[{self.session_id}] Agent socket closed while sending audio "
                f"(code={e.code}, reason={reason})"
            )
            await self._notify_client_error("Voice agent connection closed")
        except Exception as e:
            logger.error(f"[{self.session_id}] Error sending audio to agent: {e}")
    
    async def receive_from_agent(self):
        """Receive messages/audio from Deepgram Voice Agent and forward to client."""
        try:
            while self.is_active and self.agent_ws:
                try:
                    msg = await asyncio.wait_for(self.agent_ws.recv(), timeout=0.1)
                    
                    if isinstance(msg, bytes):
                        # Audio data from TTS - forward to client
                        self.audio_chunk_count += 1
                        
                        # Send playback_started on first audio chunk
                        if not self.playback_started_sent:
                            self.playback_started_sent = True
                            if self.start_time:
                                latency_ms = int((time.perf_counter() - self.start_time) * 1000)
                                logger.info(f"[{self.session_id}] Agent | ⚡ First audio (latency: {latency_ms}ms)")
                            await self.client_ws.send_text(json.dumps({
                                "type": "playback_started"
                            }))
                        
                        # Log only first audio chunk
                        if self.audio_chunk_count == 1:
                            logger.info(f"[{self.session_id}] Agent | Receiving audio chunks...")
                        
                        audio_base64 = base64.b64encode(msg).decode('utf-8')
                        await self.client_ws.send_text(json.dumps({
                            "type": "audio_chunk",
                            "audio": audio_base64,
                            "encoding": "linear16",
                            "sample_rate": 24000
                        }))
                        
                    elif isinstance(msg, str):
                        # JSON message from agent
                        await self._handle_agent_message(msg)
                            
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed as e:
                    self._mark_agent_closed()
                    reason = (e.reason or "").strip() or "no reason provided"
                    if e.code == 1005:
                        reason = "no status received from agent"
                    logger.info(
                        f"[{self.session_id}] Agent connection closed "
                        f"(code={e.code}, reason={reason})"
                    )
                    await self._notify_client_error(
                        f"Voice agent connection closed (code={e.code})"
                    )
                    break
                    
        except Exception as e:
            logger.error(f"[{self.session_id}] Error receiving from agent: {e}")
    
    async def _execute_function(self, function_name: str, arguments: dict) -> str:
        """
        Execute a function and return the result as a JSON string.
        Logs each step like the chat module for debugging.
        """
        start_time = time.perf_counter()
        
        logger.info(f"[VOICE_FUNCTION] [{self.session_id}] Starting execution: {function_name}")
        logger.info(
            f"[VOICE_FUNCTION] [{self.session_id}] Arguments payload: "
            f"{self._log_preview(arguments)}"
        )
        
        try:
            if function_name == "retrieve_documents":
                query = arguments.get("query", "")
                
                logger.info(f"[VOICE_FUNCTION] [{self.session_id}] Document retrieval: query='{query}', collection={self.settings.MONGODB_COLLECTION_NAME}")
                
                # Use retrieve_documents from tools/functions.py
                documents, token_usage = await retrieve_documents(
                    query=query,
                    collection_name=self.settings.MONGODB_COLLECTION_NAME,
                    top_k=8,
                    top_n=5
                )
                
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                logger.info(f"[VOICE_FUNCTION] [{self.session_id}] Retrieved {len(documents)} documents | tokens={token_usage} | took {elapsed_ms}ms")
                
                if documents:
                    # Format documents for voice response
                    doc_summaries = []
                    for i, doc in enumerate(documents[:3]):  # Top 3 for voice
                        content_preview = doc.page_content
                        doc_summaries.append({
                            "index": i + 1,
                            "file": doc.metadata.get("file_name", "Unknown"),
                            "content": content_preview,
                            "score": round(doc.metadata.get("score", 0), 3)
                        })
                        logger.debug(f"[VOICE_FUNCTION] [{self.session_id}] Doc {i+1}: {doc.metadata.get('file_name', 'Unknown')} (score={doc.metadata.get('score', 0):.3f})")
                    
                    result = {
                        "found": True,
                        "count": len(documents),
                        "documents": doc_summaries,
                        "message": f"Found {len(documents)} relevant documents"
                    }
                else:
                    result = {
                        "found": False,
                        "count": 0,
                        "message": "No relevant documents found for this query"
                    }
                
                result_json = json.dumps(result)
                logger.info(
                    f"[VOICE_FUNCTION] [{self.session_id}] Returning result for {function_name}: "
                    f"{self._log_preview(result_json)}"
                )
                return result_json
            
            else:
                logger.warning(f"[VOICE_FUNCTION] [{self.session_id}] Unknown function: {function_name}")
                result_json = json.dumps({"error": f"Unknown function: {function_name}"})
                logger.info(
                    f"[VOICE_FUNCTION] [{self.session_id}] Returning error result: "
                    f"{self._log_preview(result_json)}"
                )
                return result_json
                
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(f"[VOICE_FUNCTION] [{self.session_id}] Error in {function_name} after {elapsed_ms}ms: {e}")
            traceback.print_exc()
            return json.dumps({"error": str(e)})
    
    async def _handle_agent_message(self, msg: str):
        """Handle JSON message from Deepgram Voice Agent."""
        data = json.loads(msg)
        msg_type = data.get("type")
        if isinstance(msg_type, str) and "Function" in msg_type:
            logger.info(
                f"[{self.session_id}] Agent | Function event received: "
                f"type={msg_type} payload={self._log_preview(data)}"
            )
        
        if msg_type == "Welcome":
            logger.info(f"[{self.session_id}] Agent | Welcome received")
            await self.client_ws.send_text(json.dumps({
                "type": "agent_ready"
            }))
            
        elif msg_type == "SettingsApplied":
            logger.info(f"[{self.session_id}] Agent | Settings applied")
            await self.client_ws.send_text(json.dumps({
                "type": "settings_applied"
            }))
            
        elif msg_type == "UserStartedSpeaking":
            self.start_time = time.perf_counter()
            logger.info(f"[{self.session_id}] Agent | User started speaking")
            await self.client_ws.send_text(json.dumps({
                "type": "speech_started"
            }))
            
        elif msg_type == "AgentThinking":
            logger.info(f"[{self.session_id}] Agent | Thinking...")
            await self.client_ws.send_text(json.dumps({
                "type": "thinking"
            }))
            
        elif msg_type == "AgentStartedSpeaking":
            if self.start_time:
                latency_ms = int((time.perf_counter() - self.start_time) * 1000)
                logger.info(f"[{self.session_id}] Agent | ⚡ Started speaking (latency: {latency_ms}ms)")
            await self.client_ws.send_text(json.dumps({
                "type": "playback_started"
            }))
            
        elif msg_type == "AgentAudioDone":
            logger.info(f"[{self.session_id}] Agent | Audio done (total chunks: {self.audio_chunk_count})")
            # Reset for next response
            self.audio_chunk_count = 0
            self.playback_started_sent = False
            await self.client_ws.send_text(json.dumps({
                "type": "playback_finished"
            }))
            
        elif msg_type == "ConversationText":
            # Transcript or response text
            role = data.get("role")
            content = data.get("content", "")
            
            # Save raw transcript directly to our database
            try:
                self.user_data_collection.insert_one({
                    "session_id": self.session_id,
                    "role": role,
                    "content": content,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc)
                })
            except Exception as e:
                logger.error(f"[{self.session_id}] Failed to save conversation text to MongoDB: {e}")
            
            if role == "user":
                logger.info(f"[{self.session_id}] Agent | User: {content}")
                await self.client_ws.send_text(json.dumps({
                    "type": "transcript",
                    "text": content
                }))
            elif role == "assistant":
                logger.info(f"[{self.session_id}] Agent | Assistant: {content}")
                await self.client_ws.send_text(json.dumps({
                    "type": "response",
                    "text": content
                }))
        
        elif msg_type == "FunctionCallRequest":
            # Deepgram is requesting us to execute a function
            # Handle both single function format and array format
            func_name_direct = data.get("function_name") or data.get("name")
            if func_name_direct:
                functions = [data]
            else:
                functions = data.get("functions", [])
                
            logger.info(
                f"[{self.session_id}] Agent | FunctionCallRequest count={len(functions)} "
                f"payload={self._log_preview(data)}"
            )
            
            for idx, func in enumerate(functions, start=1):
                func_id = func.get("function_id") or func.get("id", "")
                func_name = func.get("function_name") or func.get("name", "")
                func_args_str = func.get("arguments", "{}")
                
                logger.info(
                    f"[{self.session_id}] Agent | FunctionCallRequest[{idx}] "
                    f"id={func_id or '<missing>'} name={func_name or '<missing>'} "
                    f"raw_arguments={self._log_preview(func_args_str)}"
                )
                
                # Parse arguments
                try:
                    func_args = json.loads(func_args_str) if isinstance(func_args_str, str) else func_args_str
                except json.JSONDecodeError:
                    logger.warning(
                        f"[{self.session_id}] Agent | FunctionCallRequest[{idx}] invalid JSON arguments; "
                        f"using empty object"
                    )
                    func_args = {}
                
                logger.info(
                    f"[{self.session_id}] Agent | FunctionCallRequest[{idx}] parsed_arguments="
                    f"{self._log_preview(func_args)}"
                )
                
                # Execute the function
                exec_start = time.perf_counter()
                result = await self._execute_function(func_name, func_args)
                exec_ms = int((time.perf_counter() - exec_start) * 1000)
                
                logger.info(
                    f"[{self.session_id}] Agent | FunctionCallRequest[{idx}] result "
                    f"(duration={exec_ms}ms): {self._log_preview(result)}"
                )
                
                # Send FunctionCallResponse back to Deepgram
                response = {
                    "type": "FunctionCallResponse",
                    "id": func_id,
                    "name": func_name,
                    "content": result
                }
                logger.info(
                    f"[{self.session_id}] Agent | FunctionCallResponse[{idx}] payload="
                    f"{self._log_preview(response)}"
                )
                
                await self.agent_ws.send(json.dumps(response))
                logger.info(
                    f"[{self.session_id}] Agent | Sent FunctionCallResponse[{idx}] "
                    f"id={func_id or '<missing>'} name={func_name or '<missing>'}"
                )
                
                # Notify client
                await self.client_ws.send_text(json.dumps({
                    "type": "function_executed",
                    "name": func_name,
                    "result": result
                }))
                
        elif msg_type == "FunctionCall":
            # Legacy handler - tool/function call from agent (server-side)
            function_name = data.get("name", "")
            function_args = data.get("arguments", {})
            logger.info(f"[{self.session_id}] Agent | Function call: {function_name}({function_args})")
            await self.client_ws.send_text(json.dumps({
                "type": "function_call",
                "name": function_name,
                "arguments": function_args
            }))
            
        elif msg_type == "FunctionCallResult":
            # Result of function call
            result = data.get("result", "")
            logger.info(f"[{self.session_id}] Agent | Function result received")
            await self.client_ws.send_text(json.dumps({
                "type": "function_result",
                "result": result
            }))
                
        elif msg_type == "Error":
            error_msg = (
                data.get("message")
                or data.get("error")
                or data.get("description")
                or f"Agent error payload: {json.dumps(data)}"
            )
            logger.error(f"[{self.session_id}] Agent | Error: {error_msg}")
            await self.client_ws.send_text(json.dumps({
                "type": "error",
                "message": error_msg
            }))
            
        else:
            logger.debug(f"[{self.session_id}] Agent | {msg_type}: {data}")
    
    async def close(self):
        """Close the Voice Agent connection."""
        self.is_active = False
        if self.agent_ws:
            try:
                await self.agent_ws.close()
            except Exception:
                pass
        
        # Close Mongo client safely
        try:
            if hasattr(self, 'mongo_client'):
                self.mongo_client.close()
        except Exception as e:
            logger.error(f"[{self.session_id}] Failed to close MongoDB client: {e}")
            
        logger.info(f"[{self.session_id}] Session closed")

