from __future__ import annotations

from typing import Any
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings

class MongoDBManager:
    """Async MongoDB client manager using Motor."""

    _client: AsyncIOMotorClient[Any] | None = None

    @classmethod
    def get_client(cls) -> AsyncIOMotorClient[Any]:
        """Get or initialize the AsyncIOMotorClient connection pool."""
        if cls._client is None:
            cls._client = AsyncIOMotorClient(settings.MONGO_URI)
        return cls._client

    @classmethod
    def get_database(cls) -> AsyncIOMotorDatabase[Any]:
        """Get the AsyncIOMotorDatabase instance."""
        client = cls.get_client()
        return client[settings.MONGO_DB_NAME]

    @classmethod
    def close(cls) -> None:
        """Close the MongoDB connection client."""
        if cls._client is not None:
            cls._client.close()
            cls._client = None

def get_mongo_db() -> AsyncIOMotorDatabase[Any]:
    """Dependency helper returning the AsyncIOMotorDatabase instance."""
    return MongoDBManager.get_database()
