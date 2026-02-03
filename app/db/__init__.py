import os

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings

settings = get_settings()


def _resolve_mongo_uri() -> str:
    env_candidates = ("MONGODB_URI", "MONGO_URI", "DATABASE_URL")
    for key in env_candidates:
        value = os.getenv(key)
        if value:
            return value
    return settings.mongodb_uri


class MongoConnection:
    client: AsyncIOMotorClient | None = None
    uri: str = _resolve_mongo_uri()


def get_db_client() -> AsyncIOMotorClient:
    if MongoConnection.client is None:
        MongoConnection.client = AsyncIOMotorClient(MongoConnection.uri)
    return MongoConnection.client


def get_database():
    client = get_db_client()
    return client[settings.mongodb_db_name]
