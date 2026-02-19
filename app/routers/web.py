import base64
import hashlib
import logging
import re
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from bson import ObjectId
from cryptography.fernet import Fernet, InvalidToken
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.db import get_database
from app.services.auth_utils import get_user_from_request, hash_password

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()
settings = get_settings()

logger = logging.getLogger(__name__)

AVATAR_MAP = {
    "male": "/static/img/avatar-male.svg",
    "female": "/static/img/avatar-female.svg",
    "default": "/static/img/avatar-neutral.svg",
}


def to_data_uri(payload):
    if not payload:
        return None
    data = payload.get("data")
    if not data:
        return None
    encoded = base64.b64encode(data).decode("utf-8")
    content_type = payload.get("content_type") or "image/png"
    return f"data:{content_type};base64,{encoded}"


def resolve_avatar(user) -> str:
    if not user:
        return AVATAR_MAP["default"]
    photo_uri = to_data_uri(user.get("profile_photo"))
    if photo_uri:
        return photo_uri
    gender = (user.get("gender") or "").lower()
    if gender in AVATAR_MAP:
        return AVATAR_MAP[gender]
    return AVATAR_MAP["default"]


def base_context(request: Request, **extra):
    context = {
        "request": request,
        "current_year": datetime.utcnow().year,
        "is_authenticated": extra.pop("is_authenticated", False),
        "show_messages": extra.pop("show_messages", False),
        "show_admin": extra.pop("show_admin", False),
        "current_user": extra.pop("current_user", None),
        "avatar_url": extra.pop("avatar_url", AVATAR_MAP["default"]),
    }
    context.update(extra)
    return context


async def build_context(request: Request, **extra):
    user = await get_user_from_request(request)
    is_authenticated = user is not None
    show_admin = bool(user and user.get("is_admin"))
    show_messages = is_authenticated
    return base_context(
        request,
        is_authenticated=is_authenticated,
        show_admin=show_admin,
        show_messages=show_messages,
        current_user=user,
        avatar_url=resolve_avatar(user),
        **extra,
    )


def _fernet() -> Fernet:
    secret = (settings.secret_key or "").encode("utf-8")
    digest = hashlib.sha256(secret).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def _encrypt_text(text: str) -> str:
    return _fernet().encrypt(text.encode("utf-8")).decode("utf-8")


def _decrypt_text(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""


def _iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.isoformat() + "Z"


def _read_key(user_id: str) -> str:
    return f"last_read_at.{user_id}"


async def _compute_unread_count(db, conversation: dict, user_id: str) -> int:
    last_read_at = (conversation.get("last_read_at") or {}).get(user_id)
    query = {
        "conversation_id": str(conversation.get("_id")),
        "sender_id": {"$ne": user_id},
    }
    if last_read_at:
        query["created_at"] = {"$gt": last_read_at}
    return await db.messages.count_documents(query)


def _is_messaging_restricted(user: dict | None) -> bool:
    if not user:
        return True
    if _is_admin_user(user):
        return False
    if user.get("restricted"):
        return True

    raw_status_any = user.get("doctor_verification_status")
    if raw_status_any is not None:
        status_any = str(raw_status_any or "").strip().lower()
        if status_any != "verified":
            return True

    role = str(user.get("role") or "").strip().lower()
    if role == "doctor":
        raw_status = (
            user.get("doctor_verification_status")
            if user.get("doctor_verification_status") is not None
            else user.get("status")
        )
        if raw_status is None:
            raw_status = user.get("verification_status")
        status = str(raw_status or "").strip().lower()
        if status != "verified":
            return True
    return False


def _admin_emails() -> list[str]:
    emails = [e.strip().lower() for e in (settings.admin_emails or []) if e]
    return sorted(set(emails))


def _is_admin_user(user: dict | None) -> bool:
    if not user:
        return False
    if user.get("is_admin") in (True, 1, "1", "true", "True", "TRUE"):
        return True
    role = str(user.get("role") or "").strip().lower()
    if role == "admin":
        return True
    email = str(user.get("email") or "").strip().lower()
    return bool(email and email in set(_admin_emails()))


async def _get_admin_users(db, ensure_mailboxes: bool = True) -> list[dict]:
    admin_emails = _admin_emails()
    admin_email_regexes = [re.compile(f"^{re.escape(e)}$", re.IGNORECASE) for e in admin_emails]
    query = {
        "$or": [
            {"is_admin": True},
            {"is_admin": {"$in": [1, "1", "true", "True", "TRUE"]}},
            {"role": {"$in": ["admin", "Admin", "ADMIN"]}},
        ]
    }
    if admin_emails:
        query["$or"].append({"email": {"$in": admin_emails}})
        query["$or"].append({"email": {"$in": admin_email_regexes}})

    users = await db.users.find(query).to_list(length=50)

    if ensure_mailboxes and admin_emails:
        now = datetime.utcnow()
        for email in admin_emails:
            email_clean = str(email or "").strip().lower()
            if not email_clean:
                continue

            # Idempotent seed: prevent duplicate admin users by using upsert keyed on email (case-insensitive)
            password = secrets.token_urlsafe(16)
            normalized_email_expr = {
                "$expr": {
                    "$eq": [
                        {"$toLower": {"$trim": {"input": "$email"}}},
                        email_clean,
                    ]
                }
            }

            # Cleanup: if duplicates already exist in DB for the same email (ignoring whitespace/case),
            # keep the oldest and delete the rest.
            dupes = (
                await db.users.find(normalized_email_expr)
                .sort("created_at", 1)
                .to_list(length=25)
            )
            if dupes:
                keep_id = dupes[0].get("_id")
                if keep_id:
                    await db.users.update_one(
                        {"_id": keep_id},
                        {"$set": {"is_admin": True, "email": email_clean}},
                    )
                delete_ids = [
                    d.get("_id")
                    for d in dupes[1:]
                    if d.get("_id") and d.get("_id") != keep_id
                ]
                if delete_ids:
                    await db.users.delete_many({"_id": {"$in": delete_ids}})
            else:
                # No existing admin mailbox user for this email -> create one (idempotent)
                await db.users.update_one(
                    {"email": email_clean},
                    {
                        "$set": {"is_admin": True, "email": email_clean},
                        "$setOnInsert": {
                            "first_name": "Admin",
                            "last_name": "",
                            "dob": "1970-01-01",
                            "phone": email_clean,
                            "password_hash": hash_password(password),
                            "role": "user",
                            "gender": None,
                            "is_otp_verified": True,
                            "doctor_verification_status": None,
                            "has_logged_in": False,
                            "created_at": now,
                        },
                    },
                    upsert=True,
                )

        users = await db.users.find(query).to_list(length=50)

    return users


async def _get_admin_ids(db) -> set[str]:
    admins = await _get_admin_users(db, ensure_mailboxes=True)
    return {str(a.get("_id")) for a in admins if a.get("_id")}


def _admin_broadcast_counterparty(
    convo: dict, user_id: str, admin_ids: set[str]
) -> str | None:
    participants = [str(pid) for pid in (convo.get("participants") or [])]
    if not participants or not admin_ids:
        return None
    admin_participants = [pid for pid in participants if pid in admin_ids]
    if not admin_participants:
        return None
    non_admin_participants = [pid for pid in participants if pid not in admin_ids]
    if len(non_admin_participants) != 1:
        return None
    if user_id in admin_ids:
        return non_admin_participants[0]
    if user_id == non_admin_participants[0]:
        return "__ADMIN__"
    return None


async def _restricted_can_access_conversation(db, user: dict, convo: dict) -> bool:
    user_id = str(user.get("_id"))
    role = str(user.get("role") or "").strip().lower()
    participants = [str(pid) for pid in (convo.get("participants") or [])]
    other_ids = [pid for pid in participants if pid != user_id]
    if not other_ids:
        return False

    admin_ids = await _get_admin_ids(db)
    # Restricted doctors may only access the admin broadcast conversation.
    if role == "doctor":
        return bool(admin_ids) and all(pid in admin_ids for pid in other_ids)
    if admin_ids and all(pid in admin_ids for pid in other_ids):
        return True

    for pid in other_ids:
        try:
            other = await db.users.find_one({"_id": ObjectId(pid)})
        except Exception:
            other = None
        if not _is_admin_user(other):
            return False
    return True


def _restricted_access_error() -> dict:
    return {
        "error": "Please wait for admin to verify your account.",
    }


def _is_admin_only_conversation(convo: dict, user_id: str, admin_ids: set[str]) -> bool:
    participants = [str(pid) for pid in (convo.get("participants") or [])]
    other_ids = [pid for pid in participants if pid != str(user_id)]
    if not other_ids:
        return False
    return all(pid in admin_ids for pid in other_ids)


async def _ensure_admin_conversation(db, user_id: str) -> str | None:
    admin_ids = sorted(_id for _id in (await _get_admin_ids(db)) if _id)
    if not admin_ids:
        return None
    participants = sorted(set([str(user_id), *[str(a) for a in admin_ids]]))
    existing = await db.conversations.find_one({"participants": participants})
    if not existing:
        existing = await db.conversations.find_one(
            {"participants": {"$all": participants}, "$expr": {"$eq": [{"$size": "$participants"}, len(participants)]}}
        )
    if existing:
        return str(existing.get("_id"))
    now = datetime.utcnow()
    result = await db.conversations.insert_one(
        {"participants": participants, "created_at": now, "updated_at": now}
    )
    return str(result.inserted_id)


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse("landing.html", await build_context(request))


@router.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse("about.html", await build_context(request))


@router.get("/contact", response_class=HTMLResponse)
async def contact(request: Request):
    return templates.TemplateResponse("contact.html", await build_context(request))


@router.get("/doctors", response_class=HTMLResponse)
async def doctors(
    request: Request,
    city: str | None = Query(None),
    pin_code: str | None = Query(None),
):
    db = get_database()
    cursor = db.users.find(
        {"role": "doctor", "doctor_verification_status": "verified"},
        {
            "first_name": 1,
            "last_name": 1,
            "specialization": 1,
            "description": 1,
            "gender": 1,
            "profile_photo": 1,
            "city": 1,
            "preferred_pin": 1,
        },
    )
    doctors_list = []
    async for doc in cursor:
        doctors_list.append(
            {
                "_id": str(doc.get("_id")),
                "name": f"Dr. {doc['first_name']} {doc['last_name']}",
                "specialization": doc.get("specialization", "General"),
                "description": (doc.get("description") or "").strip(),
                "city": (doc.get("city") or "").strip(),
                "preferred_pin": doc.get("preferred_pin"),
                "avatar_url": resolve_avatar(doc),
            }
        )

    def parse_pin(value: str | None) -> int | None:
        if not value:
            return None
        digits = "".join(ch for ch in value if ch.isdigit())
        return int(digits) if digits else None

    user_pin = parse_pin(pin_code)
    search_city = (city or "").strip().lower()

    for entry in doctors_list:
        entry_city = (entry.get("city") or "").strip().lower()
        entry_pin = parse_pin(entry.get("preferred_pin"))
        entry["city_match"] = bool(search_city and entry_city == search_city)
        entry["pin_distance"] = (
            abs(entry_pin - user_pin)
            if entry_pin is not None and user_pin is not None
            else None
        )
        entry["pin_exact_match"] = bool(entry["pin_distance"] == 0)
        entry["pin_value"] = entry_pin

    def sort_key(entry):
        city_match = 0 if not search_city else (0 if entry.get("city_match") else 1)
        pin_distance = (
            entry.get("pin_distance")
            if entry.get("pin_distance") is not None
            else 10**6
        )
        return (city_match, pin_distance, entry["name"])

    doctors_sorted = sorted(doctors_list, key=sort_key)

    return templates.TemplateResponse(
        "doctors.html",
        await build_context(
            request,
            doctors=doctors_sorted,
            search_city=city or "",
            search_pin=pin_code or "",
        ),
    )


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    return templates.TemplateResponse("auth/login.html", await build_context(request))


@router.get("/signup", response_class=HTMLResponse)
async def signup(request: Request):
    return templates.TemplateResponse("auth/signup.html", await build_context(request))


@router.get("/signup/doctor", response_class=HTMLResponse)
async def doctor_signup(request: Request):
    return templates.TemplateResponse("auth/doctor_signup.html", await build_context(request))


@router.get("/profile", response_class=HTMLResponse)
async def profile(
    request: Request,
    pending_verification: bool = Query(False),
    location_updated: bool = Query(False),
    documents_updated: bool = Query(False),
    location_error: bool = Query(False),
    documents_error: bool = Query(False),
    reverify_notice: bool = Query(False),
    license_updated: bool = Query(False),
    license_error: bool = Query(False),
):
    user = await get_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    is_doctor = user.get("role") == "doctor"
    profile_data = {
        "name": f"{user['first_name']} {user['last_name']}",
        "contact": user.get("phone"),
        "email": user.get("email"),
        "dob": user.get("dob"),
        "role": user.get("role"),
        "gender": user.get("gender"),
        "description": user.get("description"),
        "specialization": user.get("specialization"),
        "license": user.get("license"),
        "pending_verification": pending_verification,
        "doctor_verification_status": user.get("doctor_verification_status"),
        "city": user.get("city"),
        "preferred_pin": user.get("preferred_pin"),
        "admin_last_action": user.get("admin_last_action"),
        "admin_last_reason": user.get("admin_last_reason"),
    }

    documents = user.get("documents", {})
    self_photo = documents.get("self_photo")
    degree_photo = documents.get("degree_photo")
    visiting_card = documents.get("visiting_card")

    return templates.TemplateResponse(
        "profile.html",
        await build_context(
            request,
            profile=profile_data,
            pending_verification=pending_verification,
            location_updated=location_updated,
            documents_updated=documents_updated,
            location_error=location_error,
            documents_error=documents_error,
            reverify_notice=reverify_notice,
            license_updated=license_updated,
            license_error=license_error,
            is_doctor=is_doctor,
            self_photo_url=to_data_uri(self_photo),
            degree_photo_url=to_data_uri(degree_photo),
            visiting_card_url=to_data_uri(visiting_card),
            profile_avatar_url=resolve_avatar(user),
        ),
    )


@router.get("/messages", response_class=HTMLResponse)
async def messages(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db = get_database()
    user_id = str(user.get("_id"))
    threads = []

    restricted_mode = _is_messaging_restricted(user)
    admin_ids = await _get_admin_ids(db)
    role = str(user.get("role") or "").strip().lower()

    cursor = db.conversations.find({"participants": user_id}).sort("updated_at", -1)
    async for convo in cursor:
        locked = False
        if restricted_mode and role == "doctor":
            locked = not (await _restricted_can_access_conversation(db, user, convo))
        elif restricted_mode and not (await _restricted_can_access_conversation(db, user, convo)):
            continue

        admin_counterparty = _admin_broadcast_counterparty(convo, user_id, admin_ids)
        is_admin_thread = admin_counterparty is not None
        other_id = None
        if admin_counterparty and admin_counterparty != "__ADMIN__":
            other_id = admin_counterparty
        elif not is_admin_thread:
            other_id = next(
                (str(pid) for pid in (convo.get("participants", []) or []) if str(pid) != str(user_id)),
                None,
            )
        other_user = None
        if other_id:
            try:
                other_user = await db.users.find_one({"_id": ObjectId(other_id)})
            except Exception:
                other_user = None
        other_name = None
        if admin_counterparty == "__ADMIN__":
            other_name = "Admin"
        elif other_user:
            if other_user.get("role") == "doctor":
                other_name = f"Dr. {other_user.get('first_name', '')} {other_user.get('last_name', '')}".strip()
            else:
                other_name = f"{other_user.get('first_name', '')} {other_user.get('last_name', '')}".strip()
        unread_count = await _compute_unread_count(db, convo, user_id)
        threads.append(
            {
                "_id": str(convo.get("_id")),
                "title": other_name or "Conversation",
                "updated_at": convo.get("updated_at"),
                "unread_count": unread_count,
                "locked": locked,
            }
        )

    return templates.TemplateResponse(
        "messages.html",
        await build_context(request, threads=threads, conversation=None, messages=[]),
    )


@router.get("/messages/{thread_id}", response_class=HTMLResponse)
async def message_thread(request: Request, thread_id: str):
    user = await get_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if thread_id == "start-admin":
        return await start_admin_message(request)

    db = get_database()
    user_id = str(user.get("_id"))
    try:
        convo_oid = ObjectId(thread_id)
    except Exception:
        return RedirectResponse(url="/messages", status_code=303)

    convo = await db.conversations.find_one({"_id": convo_oid, "participants": user_id})
    if not convo:
        return RedirectResponse(url="/messages", status_code=303)

    if _is_messaging_restricted(user):
        if not (await _restricted_can_access_conversation(db, user, convo)):
            role = str(user.get("role") or "").strip().lower()
            if role == "doctor":
                return templates.TemplateResponse(
                    "messages.html",
                    await build_context(
                        request,
                        threads=[],
                        conversation=None,
                        messages=[],
                        error=_restricted_access_error()["error"],
                    ),
                    status_code=403,
                )
            admin_thread = await _ensure_admin_conversation(db, user_id)
            if admin_thread:
                return RedirectResponse(url=f"/messages/{admin_thread}", status_code=303)
            return RedirectResponse(url="/messages", status_code=303)

    await db.conversations.update_one(
        {"_id": convo_oid},
        {"$set": {_read_key(user_id): datetime.utcnow()}},
    )

    threads = []
    restricted_mode = _is_messaging_restricted(user)
    admin_ids = await _get_admin_ids(db)
    role = str(user.get("role") or "").strip().lower()

    cursor_threads = db.conversations.find({"participants": user_id}).sort("updated_at", -1)
    async for t in cursor_threads:
        locked = False
        if restricted_mode and role == "doctor":
            locked = not (await _restricted_can_access_conversation(db, user, t))
        elif restricted_mode and not (await _restricted_can_access_conversation(db, user, t)):
            continue

        admin_counterparty = _admin_broadcast_counterparty(t, user_id, admin_ids)
        is_admin_thread = admin_counterparty is not None
        other_id = None
        if admin_counterparty and admin_counterparty != "__ADMIN__":
            other_id = admin_counterparty
        elif not is_admin_thread:
            other_id = next(
                (str(pid) for pid in (t.get("participants", []) or []) if str(pid) != str(user_id)),
                None,
            )
        other_user = None
        if other_id:
            try:
                other_user = await db.users.find_one({"_id": ObjectId(other_id)})
            except Exception:
                other_user = None
        other_name = None
        if admin_counterparty == "__ADMIN__":
            other_name = "Admin"
        elif other_user:
            if other_user.get("role") == "doctor":
                other_name = f"Dr. {other_user.get('first_name', '')} {other_user.get('last_name', '')}".strip()
            else:
                other_name = f"{other_user.get('first_name', '')} {other_user.get('last_name', '')}".strip()
        unread_count = await _compute_unread_count(db, t, user_id)
        threads.append(
            {
                "_id": str(t.get("_id")),
                "title": other_name or "Conversation",
                "unread_count": unread_count,
                "locked": locked,
            }
        )

    messages = []
    cursor_msgs = db.messages.find({"conversation_id": str(convo_oid)}).sort("created_at", 1)
    async for msg in cursor_msgs:
        messages.append(
            {
                "sender_id": msg.get("sender_id"),
                "text": _decrypt_text(msg.get("ciphertext") or ""),
                "created_at": _iso(msg.get("created_at")),
                "is_me": msg.get("sender_id") == user_id,
            }
        )

    conversation = {"_id": str(convo_oid)}
    return templates.TemplateResponse(
        "messages.html",
        await build_context(request, threads=threads, conversation=conversation, messages=messages),
    )


@router.get("/api/messages/unread")
async def api_unread(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"unread": 0})
    db = get_database()
    user_id = str(user.get("_id"))
    total = 0
    restricted_mode = _is_messaging_restricted(user)
    admin_ids = await _get_admin_ids(db) if restricted_mode else set()

    cursor = db.conversations.find({"participants": user_id})
    async for convo in cursor:
        if restricted_mode and not (await _restricted_can_access_conversation(db, user, convo)):
            continue
        total += await _compute_unread_count(db, convo, user_id)
    return JSONResponse({"unread": total})


@router.get("/api/messages/threads")
async def api_threads(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"threads": []}, status_code=401)

    db = get_database()
    user_id = str(user.get("_id"))
    threads = []
    restricted_mode = _is_messaging_restricted(user)
    admin_ids = await _get_admin_ids(db)
    role = str(user.get("role") or "").strip().lower()

    cursor = db.conversations.find({"participants": user_id}).sort("updated_at", -1)
    async for convo in cursor:
        locked = False
        if restricted_mode and role == "doctor":
            locked = not (await _restricted_can_access_conversation(db, user, convo))
        elif restricted_mode and not (await _restricted_can_access_conversation(db, user, convo)):
            continue

        admin_counterparty = _admin_broadcast_counterparty(convo, user_id, admin_ids)
        is_admin_thread = admin_counterparty is not None
        other_id = None
        if admin_counterparty and admin_counterparty != "__ADMIN__":
            other_id = admin_counterparty
        elif not is_admin_thread:
            other_id = next(
                (str(pid) for pid in (convo.get("participants", []) or []) if str(pid) != str(user_id)),
                None,
            )
        other_user = None
        if other_id:
            try:
                other_user = await db.users.find_one({"_id": ObjectId(other_id)})
            except Exception:
                other_user = None
        other_name = None
        if admin_counterparty == "__ADMIN__":
            other_name = "Admin"
        elif other_user:
            if other_user.get("role") == "doctor":
                other_name = f"Dr. {other_user.get('first_name', '')} {other_user.get('last_name', '')}".strip()
            else:
                other_name = f"{other_user.get('first_name', '')} {other_user.get('last_name', '')}".strip()
        unread_count = await _compute_unread_count(db, convo, user_id)
        threads.append(
            {
                "_id": str(convo.get("_id")),
                "title": other_name or "Conversation",
                "unread_count": unread_count,
                "updated_at": _iso(convo.get("updated_at")),
                "locked": locked,
            }
        )
    return JSONResponse({"threads": threads})


@router.post("/api/messages/{thread_id}/send")
async def api_send_message(request: Request, thread_id: str, text: str = Form("")):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    message = (text or "").strip()
    if not message:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    db = get_database()
    user_id = str(user.get("_id"))
    try:
        convo_oid = ObjectId(thread_id)
    except Exception:
        return JSONResponse({"error": "Invalid conversation"}, status_code=400)

    convo = await db.conversations.find_one({"_id": convo_oid, "participants": user_id})
    if not convo:
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    if _is_messaging_restricted(user):
        if not (await _restricted_can_access_conversation(db, user, convo)):
            role = str(user.get("role") or "").strip().lower()
            if role == "doctor":
                return JSONResponse(_restricted_access_error(), status_code=403)
            return JSONResponse({"error": "Forbidden"}, status_code=403)

    now = datetime.utcnow()
    await db.messages.insert_one(
        {
            "conversation_id": str(convo_oid),
            "sender_id": user_id,
            "ciphertext": _encrypt_text(message),
            "created_at": now,
        }
    )
    await db.conversations.update_one({"_id": convo_oid}, {"$set": {"updated_at": now}})
    return JSONResponse(
        {
            "message": {
                "sender_id": user_id,
                "text": message,
                "created_at": _iso(now),
                "is_me": True,
            }
        }
    )


@router.get("/api/messages/{thread_id}/since")
async def api_messages_since(request: Request, thread_id: str, after: str | None = None):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"messages": []}, status_code=401)

    db = get_database()
    user_id = str(user.get("_id"))
    try:
        convo_oid = ObjectId(thread_id)
    except Exception:
        return JSONResponse({"messages": []}, status_code=400)

    convo = await db.conversations.find_one({"_id": convo_oid, "participants": user_id})
    if not convo:
        return JSONResponse({"messages": []}, status_code=403)

    if _is_messaging_restricted(user):
        if not (await _restricted_can_access_conversation(db, user, convo)):
            role = str(user.get("role") or "").strip().lower()
            if role == "doctor":
                return JSONResponse(_restricted_access_error(), status_code=403)
            return JSONResponse({"messages": []}, status_code=403)

    query = {"conversation_id": str(convo_oid)}
    if after:
        try:
            after_dt = datetime.fromisoformat(after.replace("Z", ""))
            query["created_at"] = {"$gt": after_dt}
        except Exception:
            pass
    messages = []
    cursor = db.messages.find(query).sort("created_at", 1)
    async for msg in cursor:
        messages.append(
            {
                "sender_id": msg.get("sender_id"),
                "text": _decrypt_text(msg.get("ciphertext") or ""),
                "created_at": _iso(msg.get("created_at")),
                "is_me": msg.get("sender_id") == user_id,
            }
        )

    return JSONResponse({"messages": messages})


@router.post("/api/messages/{thread_id}/read")
async def api_mark_read(request: Request, thread_id: str):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"ok": False}, status_code=401)

    db = get_database()
    user_id = str(user.get("_id"))
    try:
        convo_oid = ObjectId(thread_id)
    except Exception:
        return JSONResponse({"ok": False}, status_code=400)

    convo = await db.conversations.find_one({"_id": convo_oid, "participants": user_id})
    if not convo:
        return JSONResponse({"ok": False}, status_code=403)

    if _is_messaging_restricted(user):
        if not (await _restricted_can_access_conversation(db, user, convo)):
            role = str(user.get("role") or "").strip().lower()
            if role == "doctor":
                return JSONResponse(_restricted_access_error(), status_code=403)
            return JSONResponse({"ok": False}, status_code=403)

    await db.conversations.update_one(
        {"_id": convo_oid},
        {"$set": {_read_key(user_id): datetime.utcnow()}},
    )
    return JSONResponse({"ok": True})


@router.post("/messages/{thread_id}/send")
async def send_message(request: Request, thread_id: str, text: str = Form("")):
    user = await get_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    message = (text or "").strip()
    if not message:
        return RedirectResponse(url=f"/messages/{thread_id}", status_code=303)

    db = get_database()
    user_id = str(user.get("_id"))
    try:
        convo_oid = ObjectId(thread_id)
    except Exception:
        return RedirectResponse(url="/messages", status_code=303)

    convo = await db.conversations.find_one({"_id": convo_oid, "participants": user_id})
    if not convo:
        return RedirectResponse(url="/messages", status_code=303)

    if _is_messaging_restricted(user):
        if not (await _restricted_can_access_conversation(db, user, convo)):
            role = str(user.get("role") or "").strip().lower()
            if role == "doctor":
                return templates.TemplateResponse(
                    "messages.html",
                    await build_context(
                        request,
                        threads=[],
                        conversation=None,
                        messages=[],
                        error=_restricted_access_error()["error"],
                    ),
                    status_code=403,
                )
            admin_thread = await _ensure_admin_conversation(db, user_id)
            if admin_thread:
                return RedirectResponse(url=f"/messages/{admin_thread}", status_code=303)
            return RedirectResponse(url="/messages", status_code=303)

    now = datetime.utcnow()
    await db.messages.insert_one(
        {
            "conversation_id": str(convo_oid),
            "sender_id": user_id,
            "ciphertext": _encrypt_text(message),
            "created_at": now,
        }
    )
    await db.conversations.update_one({"_id": convo_oid}, {"$set": {"updated_at": now}})
    return RedirectResponse(url=f"/messages/{thread_id}", status_code=303)


@router.get("/messages/start/{doctor_id}")
async def start_message(request: Request, doctor_id: str):
    user = await get_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if _is_messaging_restricted(user):
        return RedirectResponse(url="/messages/start-admin", status_code=303)

    db = get_database()
    user_id = str(user.get("_id"))
    try:
        doctor_oid = ObjectId(doctor_id)
    except Exception:
        return RedirectResponse(url="/doctors", status_code=303)

    doctor = await db.users.find_one({"_id": doctor_oid, "role": "doctor"})
    if not doctor:
        return RedirectResponse(url="/doctors", status_code=303)

    if not _is_admin_user(user) and (
        doctor.get("restricted") or doctor.get("doctor_verification_status") != "verified"
    ):
        return RedirectResponse(url="/messages/start-admin", status_code=303)

    participants = sorted([user_id, str(doctor_oid)])
    existing = await db.conversations.find_one({"participants": participants})
    if existing:
        return RedirectResponse(url=f"/messages/{existing['_id']}", status_code=303)

    now = datetime.utcnow()
    result = await db.conversations.insert_one(
        {
            "participants": participants,
            "created_at": now,
            "updated_at": now,
        }
    )
    return RedirectResponse(url=f"/messages/{result.inserted_id}", status_code=303)


@router.get("/messages/start-admin")
async def start_admin_message(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    db = get_database()
    user_id = str(user.get("_id"))
    try:
        admin_ids = await _get_admin_ids(db)
        logger.info(
            "start-admin: user_id=%s role=%s status=%s doctor_verification_status=%s restricted=%s admin_emails=%s admin_ids=%s",
            user_id,
            user.get("role"),
            user.get("status"),
            user.get("doctor_verification_status"),
            user.get("restricted"),
            _admin_emails(),
            sorted(admin_ids),
        )
    except Exception:
        logger.exception("start-admin: failed resolving admin ids")

    thread_id = await _ensure_admin_conversation(db, user_id)
    if not thread_id:
        return RedirectResponse(url="/messages", status_code=303)
    return RedirectResponse(url=f"/messages/{thread_id}", status_code=303)


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if not user.get("is_admin"):
        return RedirectResponse(url="/profile", status_code=303)

    db = get_database()
    users = await db.users.find().to_list(length=200)

    users_list = []
    doctors_verified = []
    pending_verification = []

    for record in users:
        profile = {
            "_id": str(record.get("_id")),
            "name": f"{record.get('first_name', '')} {record.get('last_name', '')}".strip(),
            "email": record.get("email"),
            "phone": record.get("phone"),
            "role": "admin" if record.get("is_admin") else record.get("role"),
            "doctor_verification_status": record.get("doctor_verification_status"),
            "specialization": record.get("specialization"),
            "license": record.get("license"),
            "city": record.get("city"),
            "preferred_pin": record.get("preferred_pin"),
            "description": record.get("description"),
            "restricted": bool(record.get("restricted")),
            "self_photo_url": None,
            "degree_photo_url": None,
            "visiting_card_url": None,
            "gender": record.get("gender"),
            "avatar_url": resolve_avatar(record),
        }

        documents = record.get("documents", {})
        profile["self_photo_url"] = to_data_uri(documents.get("self_photo"))
        profile["degree_photo_url"] = to_data_uri(documents.get("degree_photo"))
        profile["visiting_card_url"] = to_data_uri(documents.get("visiting_card"))

        if record.get("role") == "doctor":
            if record.get("doctor_verification_status") == "verified":
                doctors_verified.append(profile)
            else:
                users_list.append(profile)

            if record.get("has_logged_in") and record.get("doctor_verification_status") != "verified":
                pending_verification.append(profile)
        else:
            users_list.append(profile)

    return templates.TemplateResponse(
        "dashboard/admin.html",
        await build_context(
            request,
            users=users_list,
            doctors=doctors_verified,
            pending=pending_verification,
        ),
    )
