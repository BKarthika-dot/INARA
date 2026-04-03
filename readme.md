# INARA - Interview Prep AI Voice Assistants

Inara is an intelligent, voice-first assistant designed to help students master the art of interviewing. By leveraging real-time speech processing and evaluation, Inara provides a low-pressure environment to practice, assess performance, and track progress over time.

# Tech Stack used
- Python
- HTML
- CSS
- JavaScript
- Deepgram
- MongoDB
- FastAPI

✨ Key Features

- Low-Latency Voice Interaction: Natural back-and-forth conversation powered by Deepgram.

- Real-Time Evaluation: Instant feedback on clarity, confidence, conciseness, and technical accuracy.

- Performance Analytics: Visual dashboard to track score progression and interview streaks.

- Role-Specific Simulations: Tailored interview scenarios based on student career goals.

# Pipeline

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

# ⚙️ System Architecture & Pipeline

Inara operates on a high-speed duplex pipeline to ensure the conversation feels human-like:

Capture: script.js accesses the browser microphone and captures raw PCM audio buffers.

Stream: Audio is streamed via WebSockets to the FastAPI server.

Process: FastAPI proxies the stream to the Deepgram Voice Agent.

Intelligence: Deepgram handles Speech-to-Text, passes context to the LLM, and generates Text-to-Speech synthesis.

Output: The synthesized audio and live transcripts are sent back through the WebSocket.

Playback: The browser receives the stream and plays the response immediately.

# Getting Started

Clone the repo: git clone https://github.com/BKarthika-dot/INARA

Install dependencies: pip install -r requirements.txt

Set Environment Variables: Add your DEEPGRAM_API_KEY and MONGO_URI to a .env file.

Run the App: uvicorn main:app --reload

Practice: Navigate to localhost:8000 and start your first session.
