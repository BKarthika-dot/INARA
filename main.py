import asyncio
import os
import json
import websockets
from fastapi import FastAPI, WebSocket
from dotenv import load_dotenv

import google.generativeai as genai

from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from website import auth_router, views_router
from website.mongodb import interviews_collection,feedback_collection
from datetime import datetime
from bson import ObjectId

load_dotenv()

app = FastAPI()

templates = Jinja2Templates(directory="website/templates")

# ✅ Static files
app.mount(
    "/static",
    StaticFiles(directory="website/static"),
    name="static"
)

# ✅ Routers
app.include_router(auth_router)
app.include_router(views_router)

# =========================
# 🔗 Deepgram connection
# =========================

def sts_connect():
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPGRAM_API_KEY not found")

    return websockets.connect(
        "wss://agent.deepgram.com/v1/agent/converse",
        subprotocols=["token", api_key],
    )

def load_prompt(path="prompts.txt"):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()

SYSTEM_PROMPT = load_prompt("prompts.txt")

def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    config["agent"]["think"]["prompt"] = SYSTEM_PROMPT
    return config

# =========================
# 🔌 WebSocket endpoint
# =========================

@app.websocket("/ws")
async def websocket_endpoint(browser_ws: WebSocket):
    await browser_ws.accept()

    dg_ws = await sts_connect()
    config = load_config()

    # Store transcript here
    transcript_buffer = ""

    # ⚠️ TEMP: replace with real logged-in user ID later
    current_user_id = None

    await dg_ws.send(json.dumps(config))

    async def browser_handler():
        nonlocal transcript_buffer, current_user_id

        while True:
            msg = await browser_ws.receive()

            if msg["type"] == "websocket.disconnect":
                break

            # 🔴 STOP BUTTON SIGNAL
            if msg.get("text") == "STOP_INTERVIEW":
                print("Stopping interview...")
                print("Final transcript: ",transcript_buffer)
                if transcript_buffer:
                    await interviews_collection.insert_one({
                        "user_id": ObjectId(current_user_id) if current_user_id else None,
                        "transcript": transcript_buffer,
                        "created_at": datetime.utcnow(),
                        "score": None,
                        "feedback": None
                    })
                    print("Inserted test transcript")
                await browser_ws.close()
                await dg_ws.close()
                break

            audio = msg.get("bytes")
            if audio:
                if len(audio) % 2 != 0:
                    continue
                await dg_ws.send(audio)

    async def deepgram_handler():
        nonlocal transcript_buffer

        async for msg in dg_ws:
            if isinstance(msg, str):
                data = json.loads(msg)

                print("DG MESSAGE:", data)  # 🔍 DEBUG

                # ✅ Capture conversation messages
                if data.get("type") == "ConversationText":
                    role = data.get("role")
                    content = data.get("content", "").strip()

                    if content:
                        transcript_buffer += f"{role.upper()}: {content}\n"

                await browser_ws.send_text(msg)

            elif isinstance(msg, bytes):
                await browser_ws.send_bytes(msg)

    try:
        await asyncio.gather(
            browser_handler(),
            deepgram_handler(),
            deepgram_keepalive(dg_ws),
        )
    except Exception as e:
        print("WebSocket error:", e)
    finally:
        await dg_ws.close()

# =========================
# 🎙️ Browser → Deepgram
# =========================

async def browser_to_deepgram(browser_ws: WebSocket, dg_ws):
    try:
        while True:
            msg = await browser_ws.receive()

            if msg["type"] == "websocket.disconnect":
                break

            audio = msg.get("bytes")
            if audio:
                # PCM16 must be even-length
                if len(audio) % 2 != 0:
                    continue

                await dg_ws.send(audio)

    except Exception as e:
        print("browser_to_deepgram error:", e)

# =========================
# ❤️ Keepalive (CRITICAL)
# =========================

async def deepgram_keepalive(dg_ws):
    silence = b"\x00\x00" * 2048  # ~42ms @ 48kHz mono

    while True:
        await asyncio.sleep(0.04)
        await dg_ws.send(silence)

# =========================
# 🔊 Deepgram → Browser
# =========================

async def deepgram_to_browser(dg_ws, browser_ws):
    async for msg in dg_ws:
        if isinstance(msg, str):
            # JSON events / transcripts
            await browser_ws.send_text(msg)

        elif isinstance(msg, bytes):
            # Agent TTS audio
            await browser_ws.send_bytes(msg)


# =========================
# Evaluation
# =========================


genai.configure(api_key="YOUR_API_KEY")

model = genai.GenerativeModel("gemini-1.5-flash")


def load_evaluation_prompt(transcript: str):
    with open("evaluation_prompt.txt", "r", encoding="utf-8") as file:
        template = file.read()

    return template.format(transcript=transcript)


def evaluate_with_gemini(transcript: str):
    prompt = load_evaluation_prompt(transcript)

    response = model.generate_content(prompt)

    # Clean possible markdown wrapping
    cleaned = response.text.strip().replace("```json", "").replace("```", "")

    return json.loads(cleaned)


@app.post("/evaluate/{interview_id}")
async def evaluate_interview(interview_id: str):

    # 1️⃣ Fetch transcript from interviews collection
    interview = await interviews_collection.find_one(
        {"_id": ObjectId(interview_id)}
    )

    if not interview:
        return {"error": "Interview not found"}

    transcript = interview.get("transcript")

    if not transcript:
        return {"error": "Transcript not available"}

    # 2️⃣ Evaluate
    evaluation = evaluate_with_gemini(transcript)

    # 3️⃣ Store in feedback collection
    await feedback_collection.insert_one({
        "interview_id": interview_id,
        "clarity_score": evaluation["clarity"],
        "confidence_score": evaluation["confidence"],
        "conciseness_score": evaluation["conciseness"],
        "overall_score": evaluation["overall"],
        "feedback_text": evaluation["feedback"],
        "evaluated_at": datetime.utcnow()
    })

    return {"message": "Evaluation stored successfully"}