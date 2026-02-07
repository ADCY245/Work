import base64
import hashlib
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from bson import ObjectId
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.db import get_database
from app.services.auth_utils import get_user_from_request

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()
settings = get_settings()

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

    cursor = db.conversations.find({"participants": user_id}).sort("updated_at", -1)
    async for convo in cursor:
        other_id = next((pid for pid in convo.get("participants", []) if pid != user_id), None)
        other_user = None
        if other_id:
            try:
                other_user = await db.users.find_one({"_id": ObjectId(other_id)})
            except Exception:
                other_user = None
        other_name = None
        if other_user:
            if other_user.get("role") == "doctor":
                other_name = f"Dr. {other_user.get('first_name', '')} {other_user.get('last_name', '')}".strip()
            else:
                other_name = f"{other_user.get('first_name', '')} {other_user.get('last_name', '')}".strip()
        threads.append(
            {
                "_id": str(convo.get("_id")),
                "title": other_name or "Conversation",
                "updated_at": convo.get("updated_at"),
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

    db = get_database()
    user_id = str(user.get("_id"))
    try:
        convo_oid = ObjectId(thread_id)
    except Exception:
        return RedirectResponse(url="/messages", status_code=303)

    convo = await db.conversations.find_one({"_id": convo_oid, "participants": user_id})
    if not convo:
        return RedirectResponse(url="/messages", status_code=303)

    threads = []
    cursor_threads = db.conversations.find({"participants": user_id}).sort("updated_at", -1)
    async for t in cursor_threads:
        other_id = next((pid for pid in t.get("participants", []) if pid != user_id), None)
        other_user = None
        if other_id:
            try:
                other_user = await db.users.find_one({"_id": ObjectId(other_id)})
            except Exception:
                other_user = None
        other_name = None
        if other_user:
            if other_user.get("role") == "doctor":
                other_name = f"Dr. {other_user.get('first_name', '')} {other_user.get('last_name', '')}".strip()
            else:
                other_name = f"{other_user.get('first_name', '')} {other_user.get('last_name', '')}".strip()
        threads.append({"_id": str(t.get("_id")), "title": other_name or "Conversation"})

    messages = []
    cursor_msgs = db.messages.find({"conversation_id": str(convo_oid)}).sort("created_at", 1)
    async for msg in cursor_msgs:
        messages.append(
            {
                "sender_id": msg.get("sender_id"),
                "text": _decrypt_text(msg.get("ciphertext") or ""),
                "created_at": msg.get("created_at"),
                "is_me": msg.get("sender_id") == user_id,
            }
        )

    conversation = {"_id": str(convo_oid)}
    return templates.TemplateResponse(
        "messages.html",
        await build_context(request, threads=threads, conversation=conversation, messages=messages),
    )


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

    db = get_database()
    user_id = str(user.get("_id"))
    try:
        doctor_oid = ObjectId(doctor_id)
    except Exception:
        return RedirectResponse(url="/doctors", status_code=303)

    doctor = await db.users.find_one({"_id": doctor_oid, "role": "doctor"})
    if not doctor:
        return RedirectResponse(url="/doctors", status_code=303)

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
