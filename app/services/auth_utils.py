from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Any

from bson import ObjectId
from itsdangerous import BadSignature, URLSafeSerializer
from passlib.context import CryptContext

from app.core.config import get_settings
from app.db import get_database

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def generate_otp(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def hash_otp(otp: str, secret_key: str) -> str:
    return hmac.new(secret_key.encode("utf-8"), otp.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_otp(otp: str, otp_hash: str, secret_key: str) -> bool:
    return hmac.compare_digest(hash_otp(otp, secret_key), otp_hash)


def create_session_token(payload: dict[str, Any], secret_key: str) -> str:
    serializer = URLSafeSerializer(secret_key, salt="physihome-session")
    return serializer.dumps(payload)


def decode_session_token(token: str, secret_key: str) -> dict[str, Any] | None:
    serializer = URLSafeSerializer(secret_key, salt="physihome-session")
    try:
        return serializer.loads(token)
    except BadSignature:
        return None


def utcnow() -> datetime:
    return datetime.utcnow()


async def get_user_from_request(request) -> dict[str, Any] | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    data = decode_session_token(token, settings.secret_key)
    if not data:
        return None
    user_id = data.get("user_id")
    if not user_id:
        return None
    db = get_database()
    return await db.users.find_one({"_id": ObjectId(user_id)})
