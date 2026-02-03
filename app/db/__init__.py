from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings

settings = get_settings()


class MongoConnection:
    client: AsyncIOMotorClient | None = None


def get_db_client() -> AsyncIOMotorClient:
    if MongoConnection.client is None:
        MongoConnection.client = AsyncIOMotorClient(settings.mongodb_uri)
    return MongoConnection.client


def get_database():
    client = get_db_client()
    return client[settings.mongodb_db_name]
