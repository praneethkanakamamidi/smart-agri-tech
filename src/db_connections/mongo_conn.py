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

# Validate required environment variables
if not MONGO_DB:
    raise ValueError("❌ MONGO_DB environment variable is required. Check your .env file.")

# Construct MongoDB connection URI
if MONGO_USERNAME and MONGO_PASSWORD:
    MONGO_URI = (
        f"mongodb://{MONGO_USERNAME}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/"
        f"{MONGO_DB}?authSource={MONGO_AUTH_SOURCE}&retryWrites={MONGO_RETRY_WRITES}"
    )
else:
    MONGO_URI = f"mongodb://{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}"

logger.info(f"🚀 Connecting to MongoDB at {MONGO_HOST}:{MONGO_PORT}")

# Initialize MongoDB client
try:
    client = AsyncIOMotorClient(MONGO_URI)
    database = client[MONGO_DB]
    logger.info("✅ MongoDB connection established successfully!")
except Exception as e:
    logger.error(f"❌ Failed to connect to MongoDB: {e}")
    raise e

# Function to get the MongoDB client
def get_mongo_client():
    return client

# Function to close the MongoDB connection (useful for FastAPI shutdown events)
async def close_mongo_connection():
    logger.info("🔌 Closing MongoDB connection...")
    client.close()
    logger.info("✅ MongoDB connection closed.")
