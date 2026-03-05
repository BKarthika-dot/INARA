Microphone (Browser)
   ↓
script.js captures raw audio
   ↓
WebSocket → FastAPI (/ws)
   ↓
FastAPI forwards PCM audio
   ↓
Deepgram Agent (STT → LLM → TTS)
   ↓
Audio + transcripts sent back
   ↓
FastAPI forwards to browser
   ↓
script.js plays the audio
