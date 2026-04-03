import asyncio
import os
import json
import websockets
from fastapi import FastAPI, WebSocket
from dotenv import load_dotenv
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from website import auth_router, views_router
from website.mongodb import interviews_collection, feedback_collection
from datetime import datetime
from bson import ObjectId
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from jose import jwt, JWTError
from website.security import SECRET_KEY as JWT_SECRET
# =========================
# Interview session state
# =========================


MAX_QUESTIONS = 30
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

def _decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub")
    except JWTError as e:
        print("JWT decode error:", e)
        return None

def get_user_id_from_request(request: Request) -> str | None:
    token = request.cookies.get("access_token")
    if not token:
        return None
    return _decode_token(token)

def get_user_id_from_ws(websocket: WebSocket) -> str | None:
    token = websocket.cookies.get("access_token")
    if not token:
        return None
    return _decode_token(token)

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


#loading evaluation keywords
def load_role_keywords():
    with open("role_keywords.json", "r", encoding="utf-8") as f:
        return json.load(f)

ROLE_KEYWORDS = load_role_keywords()

# =========================
# CREATE: Store interview
# =========================

async def process_interview(transcript: str, role: str, user_id=None):

    try:
        result = await interviews_collection.insert_one({
            "user_id": ObjectId(user_id) if user_id else None,
            "transcript": transcript,
            "role": role,  # ✅ IMPORTANT
            "created_at": datetime.utcnow()
        })

        print("✅ Interview saved:", result.inserted_id)

    except Exception as e:
        print("❌ Error saving interview:", e)

# =========================
# WebSocket endpoint
# =========================

@app.websocket("/ws")
async def websocket_endpoint(browser_ws: WebSocket):

    await browser_ws.accept()
    current_user_id = get_user_id_from_ws(browser_ws)
    print("WS user_id:", current_user_id) 

    dg_ws = await sts_connect()

    config = load_config()

    transcript_buffer = ""
    transcript_saved = False

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

                # ✅ Inject closing message into Deepgram so the AI speaks it
                closing_injection = {
                    "type": "InjectAgentMessage",
                    "message": "Thank you for your time and cooperation. That concludes our interview today. Your evaluation will be processed shortly. Best of luck!"
                }
                await dg_ws.send(json.dumps(closing_injection))

                # ✅ Save transcript
                if transcript_buffer and not transcript_saved:
                    role = browser_ws.cookies.get("selected_role", "web_developer")
                    await process_interview(transcript_buffer, role, current_user_id)
                    transcript_saved = True

                # ✅ Signal frontend to wait for audio then navigate
                await browser_ws.send_text(json.dumps({
                    "type": "END_INTERVIEW",
                    "message": "Thank you for your time and cooperation. That concludes the interview!"
                }))

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
                        session["role"] = content.lower().strip()
                        print("Detected role:", session["role"])

                    # Count interviewer questions
                    if role == "assistant" and "?" in content:

                        session["question_count"] += 1
                        print("Question count:", session["question_count"])

                        if session["question_count"] >= MAX_QUESTIONS:
                            print("Max questions reached — ending interview")

                            # ✅ Save transcript BEFORE signalling the frontend
                            if transcript_buffer and not transcript_saved:
                                role = browser_ws.cookies.get("selected_role", "web_developer")
                                await process_interview(transcript_buffer, role, current_user_id)
                                transcript_saved = True

                            await browser_ws.send_text(json.dumps({
                                "type": "END_INTERVIEW",
                                "message": "Thank you for your time and cooperation. That concludes the interview! Your evaluation will be processed shortly."
                            }))

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
            role = browser_ws.cookies.get("selected_role", "web_developer")  # ✅ was missing
            await process_interview(transcript_buffer, role, current_user_id)

        sessions.pop(session_id, None)
        await dg_ws.close()

#interview evaluation
def evaluate_transcript_advanced(transcript: str, role: str):

    transcript_lower = transcript.lower()
    words = transcript_lower.split()
    word_count = len(words)
    sentences = transcript.count("\n")

    # ======================
    # 🎯 CLARITY
    # ======================
    avg_sentence_length = word_count / max(sentences, 1)

    if avg_sentence_length < 8:
        clarity = 8
    elif avg_sentence_length < 15:
        clarity = 6
    else:
        clarity = 4

    # ======================
    # 🎯 CONFIDENCE
    # ======================
    fillers = ["uh", "um", "maybe", "i think", "kind of"]
    filler_count = sum(transcript_lower.count(f) for f in fillers)

    confidence = max(10 - filler_count, 3)

    # ======================
    # 🎯 CONCISENESS
    # ======================
    if word_count < 50:
        conciseness = 8
    elif word_count < 150:
        conciseness = 6
    else:
        conciseness = 4

    # ======================
    # 🎯 TECHNICAL SCORE
    # ======================
    keywords = ROLE_KEYWORDS.get(role, [])
    keyword_hits = sum(1 for kw in keywords if kw in transcript_lower)

    if keyword_hits >= 6:
        technical = 9
    elif keyword_hits >= 3:
        technical = 7
    elif keyword_hits >= 1:
        technical = 5
    else:
        technical = 3

    # ======================
    # 🎯 STRUCTURE SCORE
    # ======================
    structured = transcript.count(":")  # USER: / ASSISTANT:
    structure_score = min(structured, 10)

    # ======================
    # 🎯 OVERALL
    # ======================
    overall = int((clarity + confidence + conciseness + technical) / 4)

    feedback = f"""
    Clarity: {'Good' if clarity > 6 else 'Needs improvement'}.
    Confidence: {'Strong' if confidence > 6 else 'Moderate'}.
    Technical depth: {'Strong' if technical > 7 else 'Basic'}.
    Try to include more domain-specific terms and structured answers.
    """

    return {
        "clarity": clarity,
        "confidence": confidence,
        "conciseness": conciseness,
        "technical": technical,
        "overall": overall,
        "feedback": feedback.strip()
    }
from bson import ObjectId

# =========================
# READ: Get interview by ID
# =========================

@app.get("/interview/{interview_id}")
async def get_interview(interview_id: str):

    try:
        interview = await interviews_collection.find_one({
            "_id": ObjectId(interview_id)
        })

        if not interview:
            return {"error": "Interview not found"}

        return {
            "id": str(interview["_id"]),
            "transcript": interview.get("transcript"),
            "created_at": interview.get("created_at")
        }

    except Exception as e:
        return {"error": str(e)}
    
# =========================
# READ: Get latest interview
# =========================

@app.get("/latest-interview")
async def get_latest_interview():

    interview = await interviews_collection.find_one(
        {},
        sort=[("created_at", -1)]
    )

    if not interview:
        return {"error": "No interviews found"}

    return {
        "id": str(interview["_id"]),
        "transcript": interview.get("transcript")
    }

@app.get("/evaluate-latest")
async def evaluate_latest(request:Request):

    try:
        user_id = get_user_id_from_request(request)
        if not user_id:
            return {"error": "Not logged in"}
        
        interview = await interviews_collection.find_one(
            {"user_id": ObjectId(user_id)},
            sort=[("created_at", -1)]
        )

        if not interview:
            return {"error": "No interviews found"}

        transcript = interview.get("transcript")
        role = interview.get("role", "web_developer")

        if not transcript or len(transcript.strip()) < 20:
            return {"error": "Transcript too short to evaluate"}

        # ✅ Prevent duplicate evaluation
        existing_feedback = await feedback_collection.find_one({
            "interview_id": interview["_id"]
        })

        if existing_feedback:
            return {
                "evaluation": {
                    "clarity": existing_feedback.get("clarity_score"),
                    "confidence": existing_feedback.get("confidence_score"),
                    "conciseness": existing_feedback.get("conciseness_score"),
                    "technical": existing_feedback.get("technical_score"),
                    "overall": existing_feedback.get("overall_score"),
                    "feedback": existing_feedback.get("feedback_text")
                }
            }

        print("Evaluating role:", role)

        # ✅ RULE-BASED evaluation
        evaluation = evaluate_transcript_advanced(transcript, role)

        await feedback_collection.insert_one({
            "interview_id": interview["_id"],
            "clarity_score": evaluation["clarity"],
            "confidence_score": evaluation["confidence"],
            "conciseness_score": evaluation["conciseness"],
            "technical_score": evaluation["technical"],
            "overall_score": evaluation["overall"],
            "feedback_text": evaluation["feedback"],
            "evaluated_at": datetime.utcnow()
        })

        return {"evaluation": evaluation}

    except Exception as e:
        print("FULL ERROR:", e)
        return {"error": str(e)}
    
@app.get("/evaluation", response_class=HTMLResponse)
async def evaluation_page(request: Request):
    return templates.TemplateResponse("evaluation.html", {"request": request})


@app.get("/reports-data")
async def reports_data(request: Request):
    try:
        # Get user_id from session/cookie however your auth works
        user_id = get_user_id_from_request(request)
        if not user_id:
            return {"error": "Not logged in"}

        # Fetch all interviews for this user, sorted by date
        cursor = interviews_collection.find(
            {"user_id": ObjectId(user_id)},
            sort=[("created_at", 1)]
        )
        interviews = await cursor.to_list(length=100)

        if not interviews:
            return {"sessions": [], "streak": 0, "longest_streak": 0}

        sessions = []
        for interview in interviews:
            interview_id = interview["_id"]
            feedback = await feedback_collection.find_one({"interview_id": interview_id})

            if not feedback:
                continue

            # main.py
            sessions.append({
                "date": interview["created_at"].strftime("%Y-%m-%d"),
                "overall":     feedback.get("overall_score", 0),     # JS looks for s['overall']
                "clarity":     feedback.get("clarity_score", 0),     # JS looks for s['clarity']
                "confidence":  feedback.get("confidence_score", 0),  # JS looks for s['confidence']
                "conciseness": feedback.get("conciseness_score", 0), # JS looks for s['conciseness']
                "technical":   feedback.get("technical_score", 0),   # JS looks for s['technical']
            })

        # --- Streak calculation ---
        # Unique days that had at least one evaluated interview
        # --- Streak calculation ---
        if not sessions:
            return {
                "sessions": [],
                "streak": 0,
                "longest_streak": 0,
                "total_sessions": 0
            }

        unique_days = sorted(set(s["date"] for s in sessions))

        last_day = datetime.strptime(unique_days[-1], "%Y-%m-%d").date()
        unique_days = sorted(set(s["date"] for s in sessions))

        current_streak = 0
        longest_streak = 0
        streak = 1

        for i in range(1, len(unique_days)):
            d1 = datetime.strptime(unique_days[i - 1], "%Y-%m-%d")
            d2 = datetime.strptime(unique_days[i],     "%Y-%m-%d")
            if (d2 - d1).days == 1:
                streak += 1
            else:
                longest_streak = max(longest_streak, streak)
                streak = 1

        longest_streak = max(longest_streak, streak)

        # Check if today or yesterday is the last session (streak still alive)
        from datetime import date
        today = date.today()
        last_day = datetime.strptime(unique_days[-1], "%Y-%m-%d").date()
        days_since_last = (today - last_day).days

        if days_since_last <= 1:
            current_streak = streak
        else:
            current_streak = 0

        return {
            "sessions": sessions,
            "streak": current_streak,
            "longest_streak": longest_streak,
            "total_sessions": len(sessions)
        }

    except Exception as e:
        print("Reports error:", e)
        return {"error": str(e)}


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    return templates.TemplateResponse("reports.html", {"request": request})

@app.get("/logout")
async def logout(response: RedirectResponse):
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("user_id")
    response.delete_cookie("selected_role")
    return response

@app.get("/home", response_class=HTMLResponse)
async def get_home(request: Request):
    # This matches the 'href' in your navbar
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/debug-jwt")
async def debug_jwt(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return {"error": "no access_token cookie"}
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return {"payload": payload}
    except Exception as e:
        return {"error": str(e)}