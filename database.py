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
    
    @classmethod
    async def create_indexes(cls):
        """Create database indexes for optimal query performance"""
        try:
            db = cls.get_db()
            if not db:
                logger.warning("Database not connected, skipping index creation")
                return False
            
            # Index for pricing lookups (most frequent query)
            await db.pricing.create_index([("_id", 1)], unique=True, name="pricing_id_unique")
            logger.info("✅ Created index: pricing._id")
            
            # Index for job status lookups
            await db.job_status.create_index([("_id", 1)], unique=True, name="job_status_id_unique")
            logger.info("✅ Created index: job_status._id")
            
            # Index for historical pricing (sorted by date for archival)
            await db.pricing_history.create_index([("archived_at", -1)], name="history_archived_at")
            logger.info("✅ Created index: pricing_history.archived_at")
            
            # TTL index for automatic cleanup of old pricing history (keep for 90 days)
            await db.pricing_history.create_index(
                [("archived_at", 1)],
                expireAfterSeconds=7776000,  # 90 days
                name="history_ttl"
            )
            logger.info("✅ Created TTL index: pricing_history (90 days)")
            
            # Index for estimation logs if they exist
            await db.estimation_logs.create_index([("created_at", -1)], name="logs_created_at")
            logger.info("✅ Created index: estimation_logs.created_at")
            
            # Compound index for analytics queries
            await db.estimation_logs.create_index(
                [("architecture", 1), ("currency", 1), ("created_at", -1)],
                name="logs_analytics"
            )
            logger.info("✅ Created compound index: estimation_logs analytics")
            
            logger.info("🎯 All database indexes created successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error creating indexes: {e}")
            return False

async def get_database():
    return Database.get_db()
