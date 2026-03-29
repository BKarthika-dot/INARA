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
from website.mongodb import interviews_collection, feedback_collection

from datetime import datetime
from bson import ObjectId


# =========================
# Interview session state
# =========================

MAX_QUESTIONS = 15
sessions = {}

load_dotenv()

app = FastAPI()

templates = Jinja2Templates(directory="website/templates")

app.mount(
    "/static",
    StaticFiles(directory="website/static"),
    name="static"
)

app.include_router(auth_router)
app.include_router(views_router)


# =========================
# Deepgram connection
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
# Gemini setup
# =========================

genai.configure(api_key=os.getenv("GENAI_API_KEY"))

model = genai.GenerativeModel("gemini-1.5-flash")


def load_evaluation_prompt(transcript: str):
    with open("evaluation_prompt.txt", "r", encoding="utf-8") as file:
        template = file.read()

    return template.format(transcript=transcript)


def evaluate_with_gemini(transcript: str):

    try:

        prompt = load_evaluation_prompt(transcript)

        response = model.generate_content(prompt)

        text = response.text.strip()

        print("Gemini raw:", text)

        start = text.find("{")
        end = text.rfind("}") + 1

        if start == -1 or end == -1:
            raise ValueError("No JSON found")

        json_text = text[start:end]

        return json.loads(json_text)

    except Exception as e:

        print("Gemini evaluation error:", e)
        return None


async def store_evaluation(interview_id: ObjectId, evaluation: dict):

    await feedback_collection.insert_one({
        "interview_id": interview_id,
        "clarity_score": evaluation.get("clarity") or evaluation.get("clarity_score"),
        "confidence_score": evaluation.get("confidence") or evaluation.get("confidence_score"),
        "conciseness_score": evaluation.get("conciseness") or evaluation.get("conciseness_score"),
        "overall_score": evaluation.get("overall") or evaluation.get("overall_score"),
        "feedback_text": evaluation.get("feedback") or evaluation.get("feedback_text"),
        "evaluated_at": datetime.utcnow()
    })

    print("Evaluation inserted into feedback_collection")


async def process_interview(transcript: str, user_id=None):

    result = await interviews_collection.insert_one({
        "user_id": ObjectId(user_id) if user_id else None,
        "transcript": transcript,
        "created_at": datetime.utcnow()
    })

    interview_id = result.inserted_id

    print("Transcript saved:", interview_id)
    print("Running evaluation...")

    evaluation = evaluate_with_gemini(transcript)

    print("Evaluation result:", evaluation)

    if evaluation:
        await store_evaluation(interview_id, evaluation)
        print("Evaluation stored")
    else:
        print("Evaluation failed")


# =========================
# WebSocket endpoint
# =========================

@app.websocket("/ws")
async def websocket_endpoint(browser_ws: WebSocket):

    await browser_ws.accept()

    dg_ws = await sts_connect()

    config = load_config()

    transcript_buffer = ""
    transcript_saved = False
    current_user_id = None

    session_id = id(browser_ws)

    sessions[session_id] = {
        "role": None,
        "question_count": 0,
        "transcript": ""
    }

    await dg_ws.send(json.dumps(config))


    async def browser_handler():

        nonlocal transcript_buffer, transcript_saved, current_user_id

        while True:

            msg = await browser_ws.receive()

            if msg["type"] == "websocket.disconnect":
                print("Browser disconnected")
                break

            if msg.get("text") == "STOP_INTERVIEW":

                print("Stopping interview")
                print("Transcript:", transcript_buffer)

                if transcript_buffer and not transcript_saved:

                    await process_interview(
                        transcript_buffer,
                        current_user_id
                    )

                    transcript_saved = True

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

                if data.get("type") == "ConversationText":

                    role = data.get("role")
                    content = data.get("content", "").strip()

                    if not content:
                        continue

                    transcript_buffer += f"{role.upper()}: {content}\n"

                    session = sessions.get(session_id)

                    # Detect candidate role from first user message
                    if role == "user" and session["role"] is None:
                        session["role"] = content
                        print("Detected role:", session["role"])

                    # Count interviewer questions
                    if role == "assistant" and "?" in content:

                        session["question_count"] += 1
                        print("Question count:", session["question_count"])

                        if session["question_count"] >= MAX_QUESTIONS:

                            print("Max questions reached — ending interview")

                            await browser_ws.send_text(json.dumps({
                                "type": "ConversationText",
                                "role": "assistant",
                                "content": "Thank you for the conversation. That concludes the interview."
                            }))

                            await browser_ws.close()
                            await dg_ws.close()
                            return

            elif isinstance(msg, bytes):
                await browser_ws.send_bytes(msg)


    try:

        await asyncio.gather(
            browser_handler(),
            deepgram_handler(),
        )

    except Exception as e:
        print("WebSocket error:", e)

    finally:

        if transcript_buffer and not transcript_saved:

            print("Connection closed — saving transcript")

            await process_interview(
                transcript_buffer,
                current_user_id
            )

        sessions.pop(session_id, None)

        await dg_ws.close()

