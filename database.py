import os
from motor.motor_asyncio import AsyncIOMotorClient
import logging

logger = logging.getLogger(__name__)

# MongoDB Connection String (from env or default to docker service name)
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
DB_NAME = "archcost_db"

class Database:
    client: AsyncIOMotorClient = None
    db = None

    @classmethod
    def connect(cls):
        try:
            logger.info(f"Connecting to MongoDB at {MONGO_URL}...")
            cls.client = AsyncIOMotorClient(MONGO_URL)
            cls.db = cls.client[DB_NAME]
            logger.info("Successfully connected to MongoDB.")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise e

    @classmethod
    def close(cls):
        if cls.client:
            cls.client.close()
            logger.info("MongoDB connection closed.")

    @classmethod
    def get_db(cls):
        return cls.db

async def get_database():
    return Database.get_db()
