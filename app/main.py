from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.config import get_settings
from .db import get_database
from .routers import auth, web

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CachedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "public, max-age=604800")
        return response


static_dir = Path(__file__).parent / "static"
app.mount("/static", CachedStaticFiles(directory=static_dir), name="static")

app.include_router(web.router)
app.include_router(auth.router)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok", "app": settings.app_name}


@app.on_event("startup")
async def ensure_indexes():
    db = get_database()
    await db.conversations.create_index([("participants", 1), ("updated_at", -1)])
    await db.messages.create_index([("conversation_id", 1), ("created_at", 1)])
    await db.appointments.create_index([("doctor_id", 1), ("status", 1), ("start_at", 1), ("end_at", 1)])
    await db.appointments.create_index([("conversation_id", 1), ("status", 1), ("start_at", 1)])
    await db.users.create_index([("assigned_admin_id", 1), ("role", 1)])
