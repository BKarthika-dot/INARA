import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")
DB_NAME = os.getenv("MONGODB_DB_NAME")

if not MONGODB_URL:
    raise RuntimeError("MONGODB_URL is not set")

if not DB_NAME:
    raise RuntimeError("MONGODB_DB_NAME is not set")

client = AsyncIOMotorClient(MONGODB_URL)
db = client[DB_NAME]

# Collections
users_collection = db["users"]
interviews_collection = db["interviews"]
feedback_collection = db["feedback"]
analytics_collection = db["analytics"]
