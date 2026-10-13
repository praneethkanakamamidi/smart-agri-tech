import os
import logging
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Read variables from environment
MONGO_USERNAME = os.getenv("MONGO_USERNAME")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_HOST = os.getenv("MONGO_HOST", "smart-agri-tech-mongo")
MONGO_PORT = os.getenv("MONGO_PORT", "27017")
MONGO_DB = os.getenv("MONGO_DB")
MONGO_AUTH_SOURCE = os.getenv("MONGO_AUTH_SOURCE", "admin")
MONGO_RETRY_WRITES = os.getenv("MONGO_RETRY_WRITES", "true")

_client: AsyncIOMotorClient | None = None


def _build_uri() -> str:
    if not MONGO_DB:
        raise ValueError("❌ MONGO_DB environment variable is required. Check your .env file.")
    if MONGO_USERNAME and MONGO_PASSWORD:
        return (
            f"mongodb://{MONGO_USERNAME}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/"
            f"{MONGO_DB}?authSource={MONGO_AUTH_SOURCE}&retryWrites={MONGO_RETRY_WRITES}"
        )
    return f"mongodb://{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}"


# Function to get the MongoDB client (created on first use)
def get_mongo_client():
    global _client
    if _client is None:
        logger.info(f"🚀 Connecting to MongoDB at {MONGO_HOST}:{MONGO_PORT}")
        _client = AsyncIOMotorClient(_build_uri())
    return _client


# Function to close the MongoDB connection (useful for FastAPI shutdown events)
async def close_mongo_connection():
    global _client
    if _client is not None:
        logger.info("🔌 Closing MongoDB connection...")
        _client.close()
        _client = None
        logger.info("✅ MongoDB connection closed.")
