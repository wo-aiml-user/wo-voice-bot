import React, { useState, useEffect, useRef, useCallback } from 'react';
import MicButton from './components/MicButton';
import ChatHistory from './components/ChatHistory';
import { v4 as uuidv4 } from 'uuid';

// WebSocket URL - point to backend server
// WebSocket URL - point to backend server
const getWebSocketUrl = () => {
  // Check for backend URL in environment variables (e.g. Render URL)
  const backendUrl = import.meta.env.VITE_API_BASE_URL;
  if (backendUrl) {
    // Replace http/https with ws/wss
    return backendUrl.replace(/^http/, 'ws');
  }
  // Fallback: Connect to the same host (working with Vite proxy/ngrok)
  return `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;
};

const WS_URL = getWebSocketUrl();

// Audio configuration
const INPUT_SAMPLE_RATE = 16000;
const OUTPUT_SAMPLE_RATE = 24000;
const AUDIO_CHANNELS = 1;

function App() {
  const [isRecording, setIsRecording] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [streamingResponse, setStreamingResponse] = useState('');
  const [response, setResponse] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isAssistantSpeaking, setIsAssistantSpeaking] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState('initializing');
  const [transcriptAnalysis, setTranscriptAnalysis] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  // User info for personalized prompts
  const [userName, setUserName] = useState('');
  const [userRole, setUserRole] = useState('');
  const [userIndustry, setUserIndustry] = useState('');
  const [yearsOfExperience, setYearsOfExperience] = useState('');
  const [showUserInfoModal, setShowUserInfoModal] = useState(false);
  const [hasStartedOnce, setHasStartedOnce] = useState(false);

  const websocketRef = useRef(null);
  const audioContextRef = useRef(null);
  const playbackContextRef = useRef(null);
  const audioStreamRef = useRef(null);
  const workletNodeRef = useRef(null);
  const sessionIdRef = useRef(null);
  const audioQueueRef = useRef([]);
  const isPlayingRef = useRef(false);
  const nextPlayTimeRef = useRef(0);
  const currentTranscriptRef = useRef('');  // Current utterance
  const accumulatedTranscriptRef = useRef('');  // All user messages in current turn
  const currentResponseRef = useRef('');
  const accumulatedResponseRef = useRef('');  // All assistant responses in current turn
  const isAssistantSpeakingRef = useRef(false);  // Track speaking state for audio muting
  const chatEndRef = useRef(null);

  useEffect(() => {
    sessionIdRef.current = uuidv4();
    setConnectionStatus('ready');
    console.log('Client session ID created:', sessionIdRef.current);

    playbackContextRef.current = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: OUTPUT_SAMPLE_RATE
    });

    return () => {
      cleanup();
      if (playbackContextRef.current) {
        playbackContextRef.current.close();
      }
    };
  }, []);

  // Auto-scroll to bottom when chat updates
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory, transcript, streamingResponse, transcriptAnalysis]);

  const playNextAudioChunk = useCallback(async () => {
    if (isPlayingRef.current || audioQueueRef.current.length === 0) {
      return;
    }

    isPlayingRef.current = true;

    while (audioQueueRef.current.length > 0) {
      const audioBase64 = audioQueueRef.current.shift();

      try {
        const binaryString = atob(audioBase64);
        const len = binaryString.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) {
          bytes[i] = binaryString.charCodeAt(i);
        }

        const pcmData = new Int16Array(bytes.buffer);
        const floatData = new Float32Array(pcmData.length);
        for (let i = 0; i < pcmData.length; i++) {
          floatData[i] = pcmData[i] / 32768.0;
        }

        const audioBuffer = playbackContextRef.current.createBuffer(
          AUDIO_CHANNELS,
          floatData.length,
          OUTPUT_SAMPLE_RATE
        );
        audioBuffer.getChannelData(0).set(floatData);

        const source = playbackContextRef.current.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(playbackContextRef.current.destination);

        const currentTime = playbackContextRef.current.currentTime;
        const startTime = Math.max(currentTime, nextPlayTimeRef.current);
        source.start(startTime);
        nextPlayTimeRef.current = startTime + audioBuffer.duration;

        console.log(`Playing audio: ${floatData.length} samples, ${audioBuffer.duration.toFixed(2)}s`);
      } catch (error) {
        console.error('Error playing audio chunk:', error);
      }
    }

    isPlayingRef.current = false;
  }, []);

  const initializeWebSocket = () => {
    if (!sessionIdRef.current) {
      console.error("Session ID not initialized.");
      setConnectionStatus('error');
      return;
    }

    if (websocketRef.current && websocketRef.current.readyState === WebSocket.OPEN) {
      console.log('[WS] Already connected, skipping initialization');
      return;
    }

    const wsUrl = `${WS_URL}/api/ws/voice/${sessionIdRef.current}`;
    console.log(`[WS] 🔌 Connecting to: ${wsUrl}`);
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('[WS] ✅ WebSocket connected successfully');
      setConnectionStatus('connected');
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case 'session_started':
          console.log('Voice Agent session started');
          break;

        case 'agent_ready':
          console.log('Voice Agent ready');
          break;

        case 'settings_applied':
          console.log('Voice Agent settings applied');
          break;

        case 'speech_started':
          console.log('User speech detected');
          setIsProcessing(true);
          break;

        case 'transcript':
          console.log('Transcript:', data.text);
          // Accumulate transcripts - each transcript is a complete utterance
          if (accumulatedTranscriptRef.current) {
            accumulatedTranscriptRef.current += ' ' + data.text;
          } else {
            accumulatedTranscriptRef.current = data.text;
          }
          currentTranscriptRef.current = data.text;
          setTranscript(accumulatedTranscriptRef.current);  // Show accumulated
          break;

        case 'thinking':
          console.log('Agent thinking...');
          setIsProcessing(true);
          break;

        case 'response':
          console.log('Response:', data.text);
          // Accumulate responses - append each new response
          if (accumulatedResponseRef.current) {
            accumulatedResponseRef.current += ' ' + data.text;
          } else {
            accumulatedResponseRef.current = data.text;
          }
          currentResponseRef.current = data.text;
          setStreamingResponse(accumulatedResponseRef.current);  // Show accumulated
          break;

        case 'playback_started':
          console.log('Agent speaking started');
          setIsAssistantSpeaking(true);
          isAssistantSpeakingRef.current = true;  // Update ref for audio muting
          setIsProcessing(false);
          break;

        case 'playback_finished':
          console.log('Agent speaking finished');
          setIsAssistantSpeaking(false);
          isAssistantSpeakingRef.current = false;  // Update ref for audio muting
          finalizeResponse();
          break;

        case 'audio_chunk':
          audioQueueRef.current.push(data.audio);
          if (playbackContextRef.current.state === 'suspended') {
            playbackContextRef.current.resume();
          }
          playNextAudioChunk();
          break;

        case 'error':
          console.error('[WS] ❌ Server error:', data.message);
          setIsProcessing(false);
          setIsAnalyzing(false);
          setConnectionStatus('error');
          break;

        case 'transcript_analysis':
          console.log('[WS] 📊 Transcript analysis received:', data.analysis);
          setTranscriptAnalysis(data.analysis);
          setIsAnalyzing(false);
          break;

        default:
          console.log('[WS] 📨 Unknown message type:', data.type, data);
          break;
      }
    };

    ws.onerror = (error) => {
      console.error('[WS] ❌ WebSocket error:', error);
      console.error('[WS] Error details - readyState:', ws.readyState, 'url:', wsUrl);
      setConnectionStatus('error');
    };

    ws.onclose = (event) => {
      console.log(`[WS] 🔌 WebSocket disconnected - code: ${event.code}, reason: ${event.reason || 'none'}, clean: ${event.wasClean}`);
      if (connectionStatus !== 'error') {
        setConnectionStatus('ready');
      }
    };

    websocketRef.current = ws;
  };

  const finalizeResponse = () => {
    // Use accumulated transcript and response for full messages
    const userMsg = accumulatedTranscriptRef.current || currentTranscriptRef.current;
    const assistantMsg = accumulatedResponseRef.current || currentResponseRef.current;

    if (userMsg || assistantMsg) {
      const newChatItem = {
        id: uuidv4(),
        userMessage: userMsg,
        assistantMessage: assistantMsg,
        timestamp: new Date().toISOString()
      };

      setChatHistory(history => [...history, newChatItem]);
      setResponse({
        transcription: userMsg,
        text: assistantMsg
      });
    }

    setIsProcessing(false);
    setTranscript('');
    setStreamingResponse('');
    currentTranscriptRef.current = '';
    accumulatedTranscriptRef.current = '';  // Reset accumulated transcript
    currentResponseRef.current = '';
    accumulatedResponseRef.current = '';  // Reset accumulated response
  };

  const arrayBufferToBase64 = (buffer) => {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return window.btoa(binary);
  };

  const handleRecordingStart = async () => {
    try {
      if (connectionStatus === 'error') {
        alert('Connection error. Please reconnect.');
        return;
      }

      setIsRecording(true);
      setHasStartedOnce(true);
      setResponse(null);
      setTranscript('');
      setStreamingResponse('');
      audioQueueRef.current = [];
      nextPlayTimeRef.current = 0;

      // Only create new session if we don't have an active connection
      const needsNewSession = !websocketRef.current || websocketRef.current.readyState !== WebSocket.OPEN;

      if (needsNewSession) {
        sessionIdRef.current = uuidv4();
        initializeWebSocket();

        await new Promise((resolve, reject) => {
          const checkConnection = () => {
            if (websocketRef.current?.readyState === WebSocket.OPEN) {
              resolve();
            } else if (websocketRef.current?.readyState === WebSocket.CLOSING || websocketRef.current?.readyState === WebSocket.CLOSED) {
              reject(new Error('WebSocket connection failed to open'));
            } else {
              setTimeout(checkConnection, 100);
            }
          };
          checkConnection();
        });

        const userContext = {};
        if (userName.trim()) userContext.name = userName.trim();
        if (userRole.trim()) userContext.role = userRole.trim();
        if (userIndustry.trim()) userContext.industry = userIndustry.trim();
        if (yearsOfExperience.trim()) userContext.years_of_experience = yearsOfExperience.trim();

        websocketRef.current.send(JSON.stringify({
          type: 'start_session',
          context: Object.keys(userContext).length > 0 ? userContext : undefined
        }));
        await new Promise(resolve => setTimeout(resolve, 500));
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          sampleRate: INPUT_SAMPLE_RATE,
          channelCount: 1,
        }
      });

      audioStreamRef.current = stream;

      audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: INPUT_SAMPLE_RATE
      });

      const source = audioContextRef.current.createMediaStreamSource(stream);

      try {
        await audioContextRef.current.audioWorklet.addModule('/pcm-processor.js');

        const workletNode = new AudioWorkletNode(audioContextRef.current, 'pcm-processor');

        workletNode.port.onmessage = (event) => {
          // Don't send audio while assistant is speaking (prevents self-triggering)
          if (event.data.type === 'audio' &&
            websocketRef.current?.readyState === WebSocket.OPEN &&
            !isAssistantSpeakingRef.current) {
            const base64Data = arrayBufferToBase64(event.data.buffer);
            websocketRef.current.send(JSON.stringify({
              type: 'audio_chunk',
              audio_data: base64Data
            }));
          }
        };

        source.connect(workletNode);
        workletNode.connect(audioContextRef.current.destination);
        workletNodeRef.current = workletNode;

        console.log('Recording started with AudioWorklet at 16kHz');
      } catch (workletError) {
        console.warn('AudioWorklet not available, using ScriptProcessor:', workletError);

        const bufferSize = 4096;
        const processorNode = audioContextRef.current.createScriptProcessor(bufferSize, 1, 1);

        processorNode.onaudioprocess = (e) => {
          if (websocketRef.current?.readyState === WebSocket.OPEN) {
            const inputData = e.inputBuffer.getChannelData(0);
            const int16Array = new Int16Array(inputData.length);
            for (let i = 0; i < inputData.length; i++) {
              const s = Math.max(-1, Math.min(1, inputData[i]));
              int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            const base64Data = arrayBufferToBase64(int16Array.buffer);
            websocketRef.current.send(JSON.stringify({
              type: 'audio_chunk',
              audio_data: base64Data
            }));
          }
        };

        source.connect(processorNode);
        const silentGain = audioContextRef.current.createGain();
        silentGain.gain.value = 0;
        processorNode.connect(silentGain);
        silentGain.connect(audioContextRef.current.destination);

        workletNodeRef.current = processorNode;
        console.log('Recording started with ScriptProcessor at 16kHz');
      }

    } catch (error) {
      console.error('Failed to start recording:', error);
      alert('Failed to start recording: ' + error.message);
      setIsRecording(false);
      setConnectionStatus('error');
    }
  };

  const handleRecordingStop = async () => {
    setIsRecording(false);

    if (workletNodeRef.current) {
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }

    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    if (audioStreamRef.current) {
      audioStreamRef.current.getTracks().forEach(track => track.stop());
      audioStreamRef.current = null;
    }

    if (websocketRef.current?.readyState === WebSocket.OPEN) {
      setIsAnalyzing(true);
      websocketRef.current.send(JSON.stringify({ type: 'end_session' }));
      console.log('Recording stopped, requesting transcript analysis...');
    } else {
      console.log('Recording stopped, WebSocket not open');
    }
  };

  const handleReconnect = () => {
    cleanup();
    sessionIdRef.current = uuidv4();
    setConnectionStatus('ready');
    setResponse(null);
    setTranscript('');
    setStreamingResponse('');
    setIsProcessing(false);
    console.log('Reconnected with new session ID:', sessionIdRef.current);
  };

  const cleanup = () => {
    if (websocketRef.current) {
      if (websocketRef.current.readyState === WebSocket.OPEN) {
        websocketRef.current.send(JSON.stringify({ type: 'end_session' }));
      }
      websocketRef.current.close();
      websocketRef.current = null;
    }

    if (workletNodeRef.current) {
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }

    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    if (audioStreamRef.current) {
      audioStreamRef.current.getTracks().forEach(track => track.stop());
      audioStreamRef.current = null;
    }

    audioQueueRef.current = [];
  };

  const handleMicClick = () => {
    if (isRecording) {
      handleRecordingStop();
    } else {
      handleRecordingStart();
    }
  };

  const hasUserInfo = userName || userRole || yearsOfExperience;
  const hasConversation = chatHistory.length > 0 || transcript || streamingResponse;

  return (
    <div className="min-h-screen bg-gradient-to-b from-black via-neutral-950 to-black flex flex-col font-sans">



      {/* Main Content - Scrollable */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-4 py-6">

          {/* Header */}
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold text-white tracking-tight">Jane</h1>
            <p className="text-neutral-500 text-sm mt-1">AI Business Consultant</p>
            {hasUserInfo && !isRecording && (
              <button
                onClick={() => setShowUserInfoModal(true)}
                className="mt-2 text-xs text-neutral-500 hover:text-red-400 transition-colors"
              >
                {userName ? `Hi, ${userName}` : 'Edit profile'} →
              </button>
            )}
          </div>

          {/* Empty State - Vertically Centered */}
          {!hasConversation && !isRecording && (
            <div className="flex flex-col items-center justify-center min-h-[50vh]">
              <div className="w-16 h-16 rounded-full border border-neutral-800 flex items-center justify-center mb-6">
                <svg className="w-7 h-7 text-neutral-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
              </div>
              <h2 className="text-lg font-medium text-white mb-2">Ready to talk</h2>
              <p className="text-neutral-500 text-sm text-center max-w-[280px]">
                Tap the button below to start chatting with Jane
              </p>
            </div>
          )}

          {/* Chat Messages */}
          <div className="space-y-4">
            <ChatHistory chatHistory={chatHistory} />

            {/* Live transcript */}
            {transcript && (
              <div className="flex justify-end">
                <div className="bg-white text-black rounded-2xl rounded-tr-sm px-4 py-3 max-w-[85%] shadow-lg">
                  <p className="text-sm">{transcript}</p>
                </div>
              </div>
            )}

            {/* Streaming response */}
            {streamingResponse && (
              <div className="flex justify-start">
                <div className="bg-neutral-900 border border-neutral-800 rounded-2xl rounded-tl-sm px-4 py-3 max-w-[85%]">
                  <p className="text-sm text-neutral-200">
                    {streamingResponse}
                    {isAssistantSpeaking && <span className="inline-block w-2 h-2 bg-red-500 rounded-full ml-2 animate-pulse"></span>}
                  </p>
                </div>
              </div>
            )}

            {/* Processing indicator */}
            {isProcessing && !streamingResponse && !transcript && (
              <div className="flex justify-start">
                <div className="bg-neutral-900/50 rounded-2xl px-4 py-3">
                  <div className="flex space-x-1.5">
                    <span className="w-2 h-2 bg-red-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></span>
                    <span className="w-2 h-2 bg-red-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
                    <span className="w-2 h-2 bg-red-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
                  </div>
                </div>
              </div>
            )}

            {/* Analysis Panel */}
            {isAnalyzing && (
              <div className="bg-neutral-900/50 border border-neutral-800 rounded-xl p-4 mt-6">
                <div className="flex items-center text-sm text-neutral-400">
                  <div className="flex space-x-1 mr-3">
                    <span className="w-1.5 h-1.5 bg-red-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></span>
                    <span className="w-1.5 h-1.5 bg-red-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
                    <span className="w-1.5 h-1.5 bg-red-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
                  </div>
                  <span>Analyzing conversation...</span>
                </div>
              </div>
            )}

            {transcriptAnalysis && !isAnalyzing && (
              <div className="bg-gradient-to-b from-neutral-900 to-neutral-950 border border-neutral-800 rounded-xl p-5 mt-6">
                <div className="flex justify-between items-start mb-4">
                  <div>
                    <span className="text-xs uppercase tracking-wider text-red-500 font-medium">AINA Diagnostic Report</span>
                    <p className="text-neutral-500 text-xs mt-1">Preliminary Analysis for Implementation Team</p>
                  </div>
                  <button
                    onClick={() => setTranscriptAnalysis(null)}
                    className="text-neutral-600 hover:text-white transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                {transcriptAnalysis.error ? (
                  <p className="text-red-400 text-sm">{transcriptAnalysis.error}</p>
                ) : (
                  <div className="space-y-5">
                    {/* Client Overview */}
                    {transcriptAnalysis.client_overview && (
                      <div>
                        <span className="text-xs uppercase tracking-wider text-neutral-500 block mb-2">Client Overview</span>
                        <div className="flex flex-wrap gap-2 mb-2">
                          {transcriptAnalysis.client_overview.industry && (
                            <span className="px-3 py-1 bg-black border border-neutral-800 rounded-full text-neutral-300 text-xs">{transcriptAnalysis.client_overview.industry}</span>
                          )}
                          {transcriptAnalysis.client_overview.size && (
                            <span className="px-3 py-1 bg-black border border-neutral-800 rounded-full text-neutral-300 text-xs">{transcriptAnalysis.client_overview.size}</span>
                          )}
                        </div>
                        {transcriptAnalysis.client_overview.context && (
                          <p className="text-neutral-400 text-sm">{transcriptAnalysis.client_overview.context}</p>
                        )}
                      </div>
                    )}

                    {/* Primary Symptoms */}
                    {transcriptAnalysis.primary_symptoms && (
                      <div className="pt-4 border-t border-neutral-800">
                        <span className="text-xs uppercase tracking-wider text-amber-500 block mb-2">Primary Symptoms</span>
                        <p className="text-neutral-300 text-sm leading-relaxed">{transcriptAnalysis.primary_symptoms}</p>
                      </div>
                    )}

                    {/* Root Cause Analysis */}
                    {transcriptAnalysis.root_cause_analysis && (
                      <div className="pt-4 border-t border-neutral-800">
                        <span className="text-xs uppercase tracking-wider text-red-500 block mb-2">Root Cause Analysis</span>
                        <p className="text-neutral-300 text-sm leading-relaxed">{transcriptAnalysis.root_cause_analysis}</p>
                      </div>
                    )}

                    {/* Gap Analysis */}
                    {transcriptAnalysis.gap_analysis && (
                      <div className="pt-4 border-t border-neutral-800">
                        <span className="text-xs uppercase tracking-wider text-neutral-500 block mb-3">Gap Analysis</span>
                        <div className="grid grid-cols-2 gap-4">
                          <div className="bg-black/50 border border-neutral-800 rounded-lg p-3">
                            <span className="text-xs text-neutral-500 block mb-1">Current State</span>
                            <p className="text-neutral-400 text-sm">{transcriptAnalysis.gap_analysis.current_state || 'Not discussed'}</p>
                          </div>
                          <div className="bg-black/50 border border-green-900/30 rounded-lg p-3">
                            <span className="text-xs text-green-600 block mb-1">Desired State</span>
                            <p className="text-neutral-300 text-sm">{transcriptAnalysis.gap_analysis.desired_state || 'Not discussed'}</p>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Recommended Module */}
                    {transcriptAnalysis.recommended_module && (
                      <div className="pt-4 border-t border-neutral-800">
                        <span className="text-xs uppercase tracking-wider text-green-500 block mb-2">Recommended AINA Module</span>
                        <div className="bg-gradient-to-r from-green-950/30 to-transparent border border-green-900/30 rounded-lg p-4">
                          <p className="text-green-400 font-medium text-sm mb-1">{transcriptAnalysis.recommended_module}</p>
                          {transcriptAnalysis.recommendation_rationale && (
                            <p className="text-neutral-400 text-xs">{transcriptAnalysis.recommendation_rationale}</p>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Scroll anchor */}
            <div ref={chatEndRef} />
          </div>
        </div>
      </div>

      {/* Bottom Controls - Fixed */}
      <div className="sticky bottom-0 bg-gradient-to-t from-black via-black to-transparent pt-8 pb-6">
        <div className="max-w-2xl mx-auto px-4">
          {/* Status */}
          <div className="flex items-center justify-center mb-4 text-xs space-x-3">
            {isRecording && (
              <span className="text-red-500 flex items-center">
                <span className="w-2 h-2 bg-red-500 rounded-full mr-2 animate-pulse"></span>
                Recording
              </span>
            )}
            {isAssistantSpeaking && (
              <span className="text-white flex items-center">
                <span className="w-2 h-2 bg-white rounded-full mr-2"></span>
                Speaking
              </span>
            )}
            {!isRecording && !isAssistantSpeaking && (
              <span className="text-neutral-600">Tap to speak</span>
            )}
          </div>

          {/* Mic Button */}
          <div className="flex justify-center">
            <button
              onClick={handleMicClick}
              disabled={isProcessing || isAssistantSpeaking || (connectionStatus === 'error' && !isRecording)}
              className={`w-16 h-16 rounded-full flex items-center justify-center transition-all duration-300 ${isRecording
                ? 'bg-red-500 shadow-lg shadow-red-500/40 scale-110'
                : 'bg-gradient-to-b from-neutral-800 to-neutral-900 border border-neutral-700 hover:border-neutral-600 hover:from-neutral-700 hover:to-neutral-800'
                } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {isRecording ? (
                <svg className="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 24 24">
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
              ) : (
                <svg className="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
                  <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
                </svg>
              )}
            </button>
          </div>

          {connectionStatus === 'error' && (
            <div className="text-center mt-4">
              <button
                onClick={handleReconnect}
                className="text-sm text-red-400 hover:text-red-300 transition-colors"
              >
                Connection lost. Tap to reconnect
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;