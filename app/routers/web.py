import base64
import hashlib
import asyncio
import logging
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Body, Form, Request, Query
from fastapi.templating import Jinja2Templates
from bson import ObjectId
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.db import get_database
from app.services.auth_utils import get_user_from_request, hash_password
from app.services.whatsapp import send_whatsapp

AVATAR_MAP = {
    "default": "/static/img/avatar-neutral.svg",
    "male": "/static/img/avatar-male.svg",
    "female": "/static/img/avatar-female.svg",
}

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()
settings = get_settings()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


async def _maybe_notify_whatsapp_new_message(
    db,
    convo: dict,
    sender: dict,
    sender_id: str,
) -> None:
    try:
        participants = [str(pid) for pid in (convo.get("participants") or [])]
        recipient_ids = [pid for pid in participants if pid and pid != sender_id]
        if not recipient_ids:
            return

        sender_name = f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip() or "Someone"
        if str(sender.get("role") or "").strip().lower() == "doctor":
            sender_name = f"Dr. {sender_name}".strip()
        site_url = str(getattr(settings, "site_url", "") or "").strip()
        notify_body = f"You have received a message from {sender_name} on PhysiHome."
        if site_url:
            notify_body = notify_body + f" Open: {site_url}"

        convo_id = str(convo.get("_id") or "")
        now = datetime.utcnow()
        window_seconds = int(getattr(settings, "wa_message_notify_debounce_seconds", 600) or 600)
        threshold = now - timedelta(seconds=window_seconds)
        online_threshold = _presence_online_threshold()

        async def _notify_one(uid: str) -> None:
            try:
                other = await db.users.find_one({"_id": ObjectId(uid)})
            except Exception:
                other = None
            if not other:
                return

            if other.get("whatsapp_notifications_enabled") is False:
                return
            phone = other.get("phone")
            if not phone:
                return

            try:
                presence = await db.user_presence.find_one(
                    {"user_id": uid, "updated_at": {"$gte": online_threshold}},
                    {"updated_at": 1},
                )
                if presence:
                    return
                existing = await db.wa_message_notify.find_one(
                    {
                        "conversation_id": convo_id,
                        "recipient_id": uid,
                        "updated_at": {"$gte": threshold},
                    }
                )
                if existing:
                    return
                await db.wa_message_notify.update_one(
                    {"conversation_id": convo_id, "recipient_id": uid},
                    {"$set": {"updated_at": now}},
                    upsert=True,
                )
            except Exception:
                return

            try:
                await send_whatsapp(phone, notify_body)
            except Exception:
                return

        for rid in recipient_ids:
            asyncio.create_task(_notify_one(rid))
    except Exception:
        return



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
        "static_version": datetime.utcnow().strftime("%Y%m%d%H%M%S"),
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


def _utcnow_ms() -> datetime:
    now = datetime.utcnow()
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def _read_key(user_id: str) -> str:
    return f"last_read_at.{user_id}"


def _presence_online_threshold() -> datetime:
    seconds = int(getattr(settings, "message_presence_window_seconds", 20) or 20)
    return datetime.utcnow() - timedelta(seconds=seconds)


async def _touch_presence(db, user_id: str, thread_id: str | None = None) -> datetime:
    now = datetime.utcnow()
    await db.user_presence.update_one(
        {"user_id": user_id},
        {"$set": {"updated_at": now, "active_thread_id": thread_id or ""}},
        upsert=True,
    )
    return now


async def _online_user_ids(db, user_ids: list[str]) -> set[str]:
    ids = [uid for uid in user_ids if uid]
    if not ids:
        return set()
    threshold = _presence_online_threshold()
    cursor = db.user_presence.find(
        {"user_id": {"$in": ids}, "updated_at": {"$gte": threshold}},
        {"user_id": 1},
    )
    online = set()
    async for item in cursor:
        uid = str(item.get("user_id") or "")
        if uid:
            online.add(uid)
    return online


def _conversation_other_participant_ids(convo: dict, user_id: str) -> list[str]:
    return [
        str(pid)
        for pid in (convo.get("participants") or [])
        if str(pid or "") and str(pid) != str(user_id)
    ]


def _message_seen_by_others(convo: dict, message_created_at: datetime | None, sender_id: str) -> bool:
    if not message_created_at:
        return False
    last_read_map = convo.get("last_read_at") or {}
    for participant_id in (convo.get("participants") or []):
        pid = str(participant_id or "")
        if not pid or pid == str(sender_id):
            continue
        seen_at = last_read_map.get(pid)
        if seen_at and seen_at >= message_created_at:
            return True
    return False


def _other_last_read_at(convo: dict, user_id: str) -> datetime | None:
    last_read_map = convo.get("last_read_at") or {}
    seen_times = []
    for participant_id in (convo.get("participants") or []):
        pid = str(participant_id or "")
        if not pid or pid == str(user_id):
            continue
        seen_at = last_read_map.get(pid)
        if seen_at:
            seen_times.append(seen_at)
    return max(seen_times) if seen_times else None


async def _conversation_presence_payload(db, convo: dict, user_id: str) -> dict:
    other_ids = _conversation_other_participant_ids(convo, user_id)
    online_ids = await _online_user_ids(db, other_ids)
    return {
        "online_ids": online_ids,
        "other_online": bool(online_ids),
    }


def _message_payload(msg: dict, user_id: str, convo: dict) -> dict:
    created_at = msg.get("created_at")
    return {
        "_id": str(msg.get("_id")) if msg.get("_id") is not None else "",
        "sender_id": msg.get("sender_id"),
        "text": (_decrypt_text(msg.get("ciphertext") or "") or "").strip() if "ciphertext" in msg else (msg.get("text") or "").strip(),
        "created_at": _iso(created_at),
        "is_me": msg.get("sender_id") == user_id,
        "seen_by_other": _message_seen_by_others(convo, created_at, msg.get("sender_id")),
    }


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


def _is_physihome_info_admin(user: dict | None) -> bool:
    if not user:
        return False
    email = str(user.get("email") or "").strip().lower()
    if email not in {"info@physihome.com", "info@physihome.shop"}:
        return False
    return _is_admin_user(user)


def _is_super_admin_user(user: dict | None) -> bool:
    if not user:
        return False
    return str(user.get("email") or "").strip().lower() == "info@physihome.shop"


def _user_display_name(user: dict | None) -> str:
    if not user:
        return "User"
    name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    if (user.get("role") or "").strip().lower() == "doctor":
        return f"Dr. {name}".strip()
    return name or str(user.get("email") or "User")


def _appointment_time_label(start_at: datetime, end_at: datetime) -> str:
    start = start_at.strftime("%d %b %Y, %I:%M %p").lstrip("0")
    end = end_at.strftime("%I:%M %p").lstrip("0")
    return f"{start} - {end}"


_IST_OFFSET = timedelta(hours=5, minutes=30)


def _now_ist() -> datetime:
    return datetime.utcnow() + _IST_OFFSET


async def _insert_system_message(db, conversation_id: str, sender_id: str, text: str) -> None:
    convo_id = str(conversation_id or "").strip()
    if not convo_id:
        return
    now = datetime.utcnow()
    await db.messages.insert_one(
        {
            "conversation_id": convo_id,
            "sender_id": str(sender_id or "system"),
            "ciphertext": _encrypt_text(text),
            "created_at": now,
        }
    )
    try:
        await db.conversations.update_one({"_id": ObjectId(convo_id)}, {"$set": {"updated_at": now}})
    except Exception:
        pass


async def _auto_cancel_appointments(db, query: dict, reason: str = "expired") -> int:
    now_ist = _now_ist()
    cutoff = now_ist + timedelta(minutes=30)
    expired = await db.appointments.find(
        {
            **query,
            "status": {"$in": ["pending", "change_requested"]},
            "start_at": {"$lte": cutoff},
        }
    ).to_list(length=200)
    if not expired:
        return 0

    now = datetime.utcnow()
    ids = [e.get("_id") for e in expired if e.get("_id")]
    if ids:
        await db.appointments.update_many(
            {"_id": {"$in": ids}},
            {
                "$set": {
                    "status": "cancelled",
                    "cancelled_reason": reason,
                    "cancelled_at": now,
                    "updated_at": now,
                }
            },
        )
    for appt in expired:
        convo_id = str(appt.get("conversation_id") or "")
        if convo_id:
            await _insert_system_message(db, convo_id, "system", "Appointment has been cancelled")
        try:
            asyncio.create_task(
                _notify_appointment_cancelled(
                    db,
                    appt,
                    cancelled_by=None,
                    cause=("cancelled due to non acceptance before expiry time" if reason == "expired" else reason),
                )
            )
        except Exception:
            pass
    return len(expired)


def _parse_slot_payload(payload: dict) -> tuple[datetime | None, datetime | None, str | None]:
    date_raw = str(payload.get("date") or "").strip()
    slots_raw = payload.get("slots") or []
    if not date_raw:
        return None, None, "date is required"
    if not isinstance(slots_raw, list):
        return None, None, "slots must be a list"
    try:
        slot_hours = sorted({int(hour) for hour in slots_raw})
    except Exception:
        return None, None, "slots must be valid hours"
    if not slot_hours:
        return None, None, "select at least one slot"
    if any(hour < 0 or hour > 23 for hour in slot_hours):
        return None, None, "slots must be between 0 and 23"
    expected = list(range(slot_hours[0], slot_hours[-1] + 1))
    if slot_hours != expected:
        return None, None, "select continuous slots"
    try:
        day = datetime.strptime(date_raw, "%Y-%m-%d")
    except Exception:
        return None, None, "date must be YYYY-MM-DD"
    start_at = day.replace(hour=slot_hours[0], minute=0, second=0, microsecond=0)
    end_at = day.replace(hour=slot_hours[-1] + 1, minute=0, second=0, microsecond=0)
    return start_at, end_at, None


def _appointment_json(appt: dict, current_user_id: str) -> dict:
    approvals = appt.get("approvals") or {}
    required_ids = [str(appt.get("doctor_id") or ""), str(appt.get("patient_id") or "")]
    start_at = appt.get("start_at")
    end_at = appt.get("end_at")
    return {
        "_id": str(appt.get("_id")),
        "conversation_id": appt.get("conversation_id"),
        "doctor_id": appt.get("doctor_id"),
        "patient_id": appt.get("patient_id"),
        "doctor_name": appt.get("doctor_name"),
        "patient_name": appt.get("patient_name"),
        "mode": appt.get("mode") or "online",
        "status": appt.get("status") or "pending",
        "start_at": _iso(start_at),
        "end_at": _iso(end_at),
        "label": _appointment_time_label(start_at, end_at) if start_at and end_at else "",
        "approved_by_me": bool(approvals.get(current_user_id)),
        "approvals_count": len([uid for uid in required_ids if uid and approvals.get(uid)]),
        "change_requested_by": appt.get("change_requested_by"),
    }


async def _get_conversation_doctor_patient(db, convo: dict) -> tuple[dict | None, dict | None]:
    participant_ids = [str(pid) for pid in (convo.get("participants") or [])]
    users = []
    for pid in participant_ids:
        try:
            found = await db.users.find_one({"_id": ObjectId(pid)})
        except Exception:
            found = None
        if found:
            users.append(found)
    doctor = next((u for u in users if (u.get("role") or "").strip().lower() == "doctor"), None)
    patient = next((u for u in users if str(u.get("_id")) != str(doctor.get("_id"))), None) if doctor else None
    return doctor, patient


async def _admin_can_manage_doctor(admin: dict, doctor: dict | None) -> bool:
    if not _is_admin_user(admin) or not doctor:
        return False
    assigned = doctor.get("assigned_admin_id")
    return bool(assigned and str(assigned) == str(admin.get("_id")))


async def _build_thread_summary(db, convo: dict, user_id: str, admin_ids: set[str], online_ids: set[str]) -> dict:
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

    return {
        "_id": str(convo.get("_id")),
        "title": other_name or "Conversation",
        "updated_at": convo.get("updated_at"),
        "other_user_id": other_id or "",
        "other_online": bool(other_id and other_id in online_ids),
    }


async def _notify_appointment_fixed(db, appt: dict) -> None:
    start_at = appt.get("start_at")
    end_at = appt.get("end_at")
    if not start_at or not end_at:
        return
    body = (
        "Appointment fixed on PhysiHome: "
        f"{_appointment_time_label(start_at, end_at)} "
        f"({appt.get('mode', 'online')}). "
        f"Doctor: {appt.get('doctor_name')}. Patient: {appt.get('patient_name')}."
    )
    recipients = []
    for uid in [appt.get("doctor_id"), appt.get("patient_id")]:
        try:
            user = await db.users.find_one({"_id": ObjectId(str(uid))})
        except Exception:
            user = None
        if user and user.get("phone"):
            recipients.append(user.get("phone"))

    assigned_admin_id = appt.get("assigned_admin_id")
    if assigned_admin_id:
        try:
            admin = await db.users.find_one({"_id": ObjectId(str(assigned_admin_id))})
        except Exception:
            admin = None
        if admin and admin.get("phone"):
            recipients.append(admin.get("phone"))

    for phone in recipients:
        asyncio.create_task(send_whatsapp(phone, body))


async def _notify_appointment_cancelled(
    db,
    appt: dict,
    cancelled_by: dict | None,
    cause: str,
) -> None:
    start_at = appt.get("start_at")
    end_at = appt.get("end_at")
    if not start_at or not end_at:
        return

    cancelled_by_label = "System"
    if cancelled_by:
        role = str(cancelled_by.get("role") or "").strip().lower()
        if role == "doctor":
            cancelled_by_label = _user_display_name(cancelled_by)
        elif role in {"admin", "superadmin"} or _is_admin_user(cancelled_by):
            cancelled_by_label = "Admin"
        else:
            cancelled_by_label = _user_display_name(cancelled_by)

    cause_text = str(cause or "cancelled").strip()
    body = (
        "Appointment cancelled on PhysiHome: "
        f"{_appointment_time_label(start_at, end_at)} "
        f"({appt.get('mode', 'online')}). "
        f"Doctor: {appt.get('doctor_name')}. Patient: {appt.get('patient_name')}. "
        f"Cause: {cause_text}. Cancelled by: {cancelled_by_label}."
    )

    recipients: list[str] = []
    for uid in [appt.get("doctor_id"), appt.get("patient_id")]:
        try:
            user = await db.users.find_one({"_id": ObjectId(str(uid))})
        except Exception:
            user = None
        if not user:
            continue
        if user.get("whatsapp_notifications_enabled") is False:
            continue
        if user.get("phone"):
            recipients.append(user.get("phone"))

    for phone in recipients:
        asyncio.create_task(send_whatsapp(phone, body))


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


async def _get_admin_ids(db, ensure_mailboxes: bool = True) -> set[str]:
    admins = await _get_admin_users(db, ensure_mailboxes=ensure_mailboxes)
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

    admin_ids = await _get_admin_ids(db, ensure_mailboxes=False)
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

    user_id_str = str(user_id)
    admin_set = set(str(a) for a in admin_ids)

    # Reuse any existing broadcast conversation between the user and admins.
    # This avoids duplicating threads when the admin list changes (e.g., admins added/removed).
    cursor = db.conversations.find({"participants": user_id_str}).sort("updated_at", -1)
    async for convo in cursor:
        participants = [str(pid) for pid in (convo.get("participants") or [])]
        if user_id_str not in participants:
            continue
        other_ids = [pid for pid in participants if pid != user_id_str]
        if other_ids and all(pid in admin_set for pid in other_ids):
            return str(convo.get("_id"))

    participants = sorted(set([user_id_str, *sorted(admin_set)]))
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


@router.get("/services", response_class=HTMLResponse)
async def services(request: Request):
    return templates.TemplateResponse("services.html", await build_context(request))


@router.get("/mobile-physiotherapy", response_class=HTMLResponse)
async def mobile_physiotherapy(request: Request):
    return templates.TemplateResponse(
        "mobile_physiotherapy.html", await build_context(request)
    )


@router.get("/what-we-treat", response_class=HTMLResponse)
async def what_we_treat(request: Request):
    return templates.TemplateResponse("what_we_treat.html", await build_context(request))


@router.get("/areas-we-cover", response_class=HTMLResponse)
async def areas_we_cover(request: Request):
    return templates.TemplateResponse("areas_we_cover.html", await build_context(request))


@router.get("/faq", response_class=HTMLResponse)
async def faq(request: Request):
    return templates.TemplateResponse("faq.html", await build_context(request))


@router.get("/doctors", response_class=HTMLResponse)
async def doctors(
    request: Request,
    city: str | None = Query(None),
    pin_code: str | None = Query(None),
):
    db = get_database()
    search_city_raw = (city or "").strip()
    search_city = search_city_raw.lower()
    search_pin_raw = "".join(ch for ch in (pin_code or "") if ch.isdigit())[:6]

    def parse_pin(value: str | None) -> int | None:
        if not value:
            return None
        digits = "".join(ch for ch in value if ch.isdigit())
        return int(digits) if digits else None

    def pin_prefix_rank(entry_pin: str, requested_pin: str) -> int:
        if not entry_pin or not requested_pin:
            return 5
        if entry_pin == requested_pin:
            return 0
        for prefix_len, rank in ((5, 1), (4, 2), (3, 3)):
            if len(entry_pin) >= prefix_len and len(requested_pin) >= prefix_len:
                if entry_pin[:prefix_len] == requested_pin[:prefix_len]:
                    return rank
        return 4

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

    user_pin = parse_pin(search_pin_raw)

    for entry in doctors_list:
        entry_city = (entry.get("city") or "").strip().lower()
        entry_pin_raw = "".join(ch for ch in str(entry.get("preferred_pin") or "") if ch.isdigit())[:6]
        entry_pin = parse_pin(entry_pin_raw)
        entry["city_match"] = bool(search_city and entry_city == search_city)
        entry["pin_distance"] = (
            abs(entry_pin - user_pin)
            if entry_pin is not None and user_pin is not None
            else None
        )
        entry["pin_exact_match"] = bool(entry["pin_distance"] == 0)
        entry["pin_prefix_rank"] = pin_prefix_rank(entry_pin_raw, search_pin_raw)
        entry["pin_nearby_match"] = bool(search_pin_raw and entry["pin_prefix_rank"] in {1, 2, 3})
        entry["pin_value"] = entry_pin

    def sort_key(entry):
        city_match = 0 if not search_city else (0 if entry.get("city_match") else 1)
        pin_rank = entry.get("pin_prefix_rank", 5) if search_pin_raw else 5
        pin_distance = (
            entry.get("pin_distance")
            if entry.get("pin_distance") is not None
            else 10**6
        )
        return (city_match, pin_rank, pin_distance, entry["name"])

    doctors_sorted = sorted(doctors_list, key=sort_key)
    ranked_matches = [
        entry
        for entry in doctors_sorted
        if (
            (search_city and entry.get("city_match"))
            or (search_pin_raw and entry.get("pin_prefix_rank", 5) < 5)
        )
    ]
    visible_doctors = ranked_matches if ranked_matches else doctors_sorted

    return templates.TemplateResponse(
        "doctors.html",
        await build_context(
            request,
            doctors=visible_doctors,
            search_city=search_city_raw,
            search_pin=search_pin_raw,
            result_count=len(visible_doctors),
            showing_filtered=bool(search_city or search_pin_raw),
            found_ranked_matches=bool(ranked_matches),
        ),
    )


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    return templates.TemplateResponse("auth/login.html", await build_context(request))


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password(request: Request):
    return templates.TemplateResponse(
        "auth/forgot_password.html", await build_context(request)
    )


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
    await _touch_presence(db, user_id)
    threads = []

    restricted_mode = _is_messaging_restricted(user)
    admin_ids = await _get_admin_ids(db, ensure_mailboxes=False)
    role = str(user.get("role") or "").strip().lower()
    convo_list = await db.conversations.find({"participants": user_id}).sort("updated_at", -1).to_list(length=200)
    other_ids = []
    for convo in convo_list:
        other_ids.extend(_conversation_other_participant_ids(convo, user_id))
    online_ids = await _online_user_ids(db, other_ids)

    for convo in convo_list:
        locked = False
        if restricted_mode and role == "doctor":
            locked = not (await _restricted_can_access_conversation(db, user, convo))
        elif restricted_mode and not (await _restricted_can_access_conversation(db, user, convo)):
            continue

        unread_count = await _compute_unread_count(db, convo, user_id)
        summary = await _build_thread_summary(db, convo, user_id, admin_ids, online_ids)
        summary["unread_count"] = unread_count
        summary["locked"] = locked
        threads.append(summary)

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
    await _touch_presence(db, user_id, thread_id)
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
    admin_ids = await _get_admin_ids(db, ensure_mailboxes=False)
    role = str(user.get("role") or "").strip().lower()
    convo_list = await db.conversations.find({"participants": user_id}).sort("updated_at", -1).to_list(length=200)
    other_ids = []
    for thread in convo_list:
        other_ids.extend(_conversation_other_participant_ids(thread, user_id))
    online_ids = await _online_user_ids(db, other_ids)

    for t in convo_list:
        locked = False
        if restricted_mode and role == "doctor":
            locked = not (await _restricted_can_access_conversation(db, user, t))
        elif restricted_mode and not (await _restricted_can_access_conversation(db, user, t)):
            continue

        unread_count = await _compute_unread_count(db, t, user_id)
        summary = await _build_thread_summary(db, t, user_id, admin_ids, online_ids)
        summary["unread_count"] = unread_count
        summary["locked"] = locked
        threads.append(summary)

    messages = []
    cursor_msgs = db.messages.find({"conversation_id": str(convo_oid)}).sort("created_at", 1)
    async for msg in cursor_msgs:
        messages.append(_message_payload(msg, user_id, convo))

    conversation_summary = await _build_thread_summary(db, convo, user_id, admin_ids, online_ids)

    doctor, patient = await _get_conversation_doctor_patient(db, convo)
    calendar_supported = bool(doctor and patient)
    can_propose_calendar = bool(calendar_supported and str(doctor.get("_id")) == user_id)
    conversation = {
        "_id": str(convo_oid),
        "title": conversation_summary.get("title") or "Conversation",
        "other_online": conversation_summary.get("other_online", False),
        "other_last_read_at": _iso(_other_last_read_at(convo, user_id)),
        "calendar_supported": calendar_supported,
        "can_propose_calendar": can_propose_calendar,
    }
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
    await _touch_presence(db, user_id)
    total = 0
    restricted_mode = _is_messaging_restricted(user)
    admin_ids = await _get_admin_ids(db, ensure_mailboxes=False) if restricted_mode else set()

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
    await _touch_presence(db, user_id)
    threads = []
    restricted_mode = _is_messaging_restricted(user)
    admin_ids = await _get_admin_ids(db, ensure_mailboxes=False)
    role = str(user.get("role") or "").strip().lower()
    convo_list = await db.conversations.find({"participants": user_id}).sort("updated_at", -1).to_list(length=200)
    other_ids = []
    for convo in convo_list:
        other_ids.extend(_conversation_other_participant_ids(convo, user_id))
    online_ids = await _online_user_ids(db, other_ids)

    for convo in convo_list:
        locked = False
        if restricted_mode and role == "doctor":
            locked = not (await _restricted_can_access_conversation(db, user, convo))
        elif restricted_mode and not (await _restricted_can_access_conversation(db, user, convo)):
            continue

        unread_count = await _compute_unread_count(db, convo, user_id)
        summary = await _build_thread_summary(db, convo, user_id, admin_ids, online_ids)
        summary["unread_count"] = unread_count
        summary["updated_at"] = _iso(convo.get("updated_at"))
        summary["locked"] = locked
        threads.append(summary)
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
    await _touch_presence(db, user_id, thread_id)
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

    now = _utcnow_ms()
    insert_result = await db.messages.insert_one(
        {
            "conversation_id": str(convo_oid),
            "sender_id": user_id,
            "ciphertext": _encrypt_text(message),
            "created_at": now,
        }
    )
    await db.conversations.update_one({"_id": convo_oid}, {"$set": {"updated_at": now}})

    await _maybe_notify_whatsapp_new_message(db, convo, user, user_id)

    return JSONResponse(
        {
            "message": {
                "_id": str(insert_result.inserted_id),
                "sender_id": user_id,
                "text": message,
                "created_at": _iso(now),
                "is_me": True,
                "seen_by_other": False,
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
    await _touch_presence(db, user_id, thread_id)
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
        messages.append(_message_payload(msg, user_id, convo))

    presence = await _conversation_presence_payload(db, convo, user_id)
    return JSONResponse(
        {
            "messages": messages,
            "other_online": presence["other_online"],
            "other_last_read_at": _iso(_other_last_read_at(convo, user_id)),
        }
    )


@router.post("/api/messages/{thread_id}/read")
async def api_mark_read(request: Request, thread_id: str):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"ok": False}, status_code=401)

    db = get_database()
    user_id = str(user.get("_id"))
    await _touch_presence(db, user_id, thread_id)
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


@router.post("/api/messages/presence")
async def api_message_presence(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"ok": False}, status_code=401)

    thread_id = request.query_params.get("thread_id")
    if not thread_id:
        try:
            form = await request.form()
            thread_id = form.get("thread_id")
        except Exception:
            thread_id = None

    db = get_database()
    user_id = str(user.get("_id"))
    await _touch_presence(db, user_id, thread_id)

    if not thread_id:
        return JSONResponse({"ok": True})

    try:
        convo_oid = ObjectId(thread_id)
    except Exception:
        return JSONResponse({"ok": True})

    convo = await db.conversations.find_one({"_id": convo_oid, "participants": user_id})
    if not convo:
        return JSONResponse({"ok": True})

    presence = await _conversation_presence_payload(db, convo, user_id)
    return JSONResponse(
        {
            "ok": True,
            "other_online": presence["other_online"],
            "other_last_read_at": _iso(_other_last_read_at(convo, user_id)),
        }
    )


@router.post("/api/messages/presence/offline")
async def api_message_presence_offline(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"ok": False}, status_code=401)

    thread_id = request.query_params.get("thread_id")
    if not thread_id:
        try:
            form = await request.form()
            thread_id = form.get("thread_id")
        except Exception:
            thread_id = None

    db = get_database()
    user_id = str(user.get("_id"))
    await db.user_presence.update_one(
        {"user_id": user_id},
        {"$set": {"updated_at": datetime.utcfromtimestamp(0), "active_thread_id": thread_id or ""}},
        upsert=True,
    )
    return JSONResponse({"ok": True})


@router.get("/api/messages/{thread_id}/calendar")
async def api_message_calendar(request: Request, thread_id: str):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    db = get_database()
    user_id = str(user.get("_id"))
    try:
        convo_oid = ObjectId(thread_id)
    except Exception:
        return JSONResponse({"error": "Invalid conversation"}, status_code=400)

    convo = await db.conversations.find_one({"_id": convo_oid, "participants": user_id})
    if not convo:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    if _is_messaging_restricted(user) and not (await _restricted_can_access_conversation(db, user, convo)):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    doctor, patient = await _get_conversation_doctor_patient(db, convo)
    if not doctor or not patient:
        return JSONResponse({"error": "Calendar is available for doctor-patient chats only"}, status_code=400)

    is_doctor = str(doctor.get("_id")) == user_id
    is_patient = str(patient.get("_id")) == user_id
    if not (is_doctor or is_patient):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    await _auto_cancel_appointments(db, {"conversation_id": str(convo_oid)})

    appointments = await db.appointments.find(
        {
            "conversation_id": str(convo_oid),
            "status": {"$in": ["pending", "booked", "change_requested"]},
        }
    ).sort("start_at", 1).to_list(length=50)

    return JSONResponse(
        {
            "doctor_id": str(doctor.get("_id")),
            "patient_id": str(patient.get("_id")),
            "doctor_name": _user_display_name(doctor),
            "patient_name": _user_display_name(patient),
            "can_propose": is_doctor,
            "can_delete_appointments": _is_physihome_info_admin(user),
            "appointments": [_appointment_json(a, user_id) for a in appointments],
        }
    )


@router.post("/api/messages/{thread_id}/appointments")
async def api_propose_appointment(request: Request, thread_id: str, payload: dict = Body(...)):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if (user.get("role") or "").strip().lower() != "doctor":
        return JSONResponse({"error": "Only doctors can share appointment slots"}, status_code=403)

    db = get_database()
    user_id = str(user.get("_id"))
    try:
        convo_oid = ObjectId(thread_id)
    except Exception:
        return JSONResponse({"error": "Invalid conversation"}, status_code=400)

    convo = await db.conversations.find_one({"_id": convo_oid, "participants": user_id})
    if not convo:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    if _is_messaging_restricted(user) and not (await _restricted_can_access_conversation(db, user, convo)):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    doctor, patient = await _get_conversation_doctor_patient(db, convo)
    if not doctor or not patient or str(doctor.get("_id")) != user_id:
        return JSONResponse({"error": "Doctor-patient conversation required"}, status_code=400)

    start_at, end_at, error = _parse_slot_payload(payload)
    if error:
        return JSONResponse({"error": error}, status_code=400)

    now_ist = _now_ist()
    if not start_at or start_at <= (now_ist + timedelta(minutes=30)):
        return JSONResponse({"error": "Select a slot at least 30 minutes from now"}, status_code=400)

    overlap = await db.appointments.find_one(
        {
            "doctor_id": user_id,
            "status": "booked",
            "start_at": {"$lt": end_at},
            "end_at": {"$gt": start_at},
        }
    )
    if overlap:
        return JSONResponse({"error": "That slot is already booked"}, status_code=409)

    now = datetime.utcnow()
    appt = {
        "conversation_id": str(convo_oid),
        "doctor_id": user_id,
        "patient_id": str(patient.get("_id")),
        "doctor_name": _user_display_name(doctor),
        "patient_name": _user_display_name(patient),
        "assigned_admin_id": doctor.get("assigned_admin_id"),
        "mode": str(payload.get("mode") or "online").strip().lower(),
        "status": "pending",
        "start_at": start_at,
        "end_at": end_at,
        "approvals": {user_id: True},
        "created_by": user_id,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.appointments.insert_one(appt)
    appt["_id"] = result.inserted_id

    await db.messages.insert_one(
        {
            "conversation_id": str(convo_oid),
            "sender_id": user_id,
            "ciphertext": _encrypt_text(f"Appointment slot shared: {_appointment_time_label(start_at, end_at)}"),
            "created_at": now,
            "appointment_id": str(result.inserted_id),
        }
    )
    await db.conversations.update_one({"_id": convo_oid}, {"$set": {"updated_at": now}})
    return JSONResponse({"appointment": _appointment_json(appt, user_id)})


@router.post("/api/appointments/{appointment_id}/approve")
async def api_approve_appointment(request: Request, appointment_id: str):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    db = get_database()
    user_id = str(user.get("_id"))
    try:
        appt_oid = ObjectId(appointment_id)
    except Exception:
        return JSONResponse({"error": "Invalid appointment"}, status_code=400)

    appt = await db.appointments.find_one({"_id": appt_oid})
    if not appt:
        return JSONResponse({"error": "Appointment not found"}, status_code=404)
    if user_id not in {str(appt.get("doctor_id")), str(appt.get("patient_id"))}:
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    status_now = str(appt.get("status") or "pending")
    if status_now in {"pending", "change_requested"}:
        start_at = appt.get("start_at")
        if start_at and start_at <= (_now_ist() + timedelta(minutes=30)):
            now = datetime.utcnow()
            await db.appointments.update_one(
                {"_id": appt_oid},
                {
                    "$set": {
                        "status": "cancelled",
                        "cancelled_reason": "expired",
                        "cancelled_at": now,
                        "updated_at": now,
                    }
                },
            )
            conversation_id = str(appt.get("conversation_id") or "")
            if conversation_id:
                await _insert_system_message(db, conversation_id, "system", "Appointment has been cancelled")
            return JSONResponse({"error": "Appointment request expired"}, status_code=409)

    approvals = appt.get("approvals") or {}
    approvals[user_id] = True
    status = appt.get("status") or "pending"
    doctor_id = str(appt.get("doctor_id"))
    patient_id = str(appt.get("patient_id"))
    if approvals.get(doctor_id) and approvals.get(patient_id):
        overlap = await db.appointments.find_one(
            {
                "_id": {"$ne": appt_oid},
                "doctor_id": doctor_id,
                "status": "booked",
                "start_at": {"$lt": appt.get("end_at")},
                "end_at": {"$gt": appt.get("start_at")},
            }
        )
        if overlap:
            return JSONResponse({"error": "That slot is already booked"}, status_code=409)
        status = "booked"

    await db.appointments.update_one(
        {"_id": appt_oid},
        {"$set": {"approvals": approvals, "status": status, "updated_at": datetime.utcnow()}},
    )
    updated = await db.appointments.find_one({"_id": appt_oid})
    if status == "booked":
        await _notify_appointment_fixed(db, updated)
    return JSONResponse({"appointment": _appointment_json(updated, user_id)})


@router.post("/api/appointments/{appointment_id}/reschedule")
async def api_reschedule_appointment(request: Request, appointment_id: str, payload: dict = Body(...)):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    db = get_database()
    user_id = str(user.get("_id"))
    try:
        appt_oid = ObjectId(appointment_id)
    except Exception:
        return JSONResponse({"error": "Invalid appointment"}, status_code=400)

    appt = await db.appointments.find_one({"_id": appt_oid})
    if not appt:
        return JSONResponse({"error": "Appointment not found"}, status_code=404)

    doctor = await db.users.find_one({"_id": ObjectId(str(appt.get("doctor_id")))})
    allowed = user_id in {str(appt.get("doctor_id")), str(appt.get("patient_id"))}
    if not allowed and not (await _admin_can_manage_doctor(user, doctor)):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    start_at, end_at, error = _parse_slot_payload(payload)
    if error:
        return JSONResponse({"error": error}, status_code=400)

    overlap = await db.appointments.find_one(
        {
            "_id": {"$ne": appt_oid},
            "doctor_id": str(appt.get("doctor_id")),
            "status": "booked",
            "start_at": {"$lt": end_at},
            "end_at": {"$gt": start_at},
        }
    )
    if overlap:
        return JSONResponse({"error": "That slot is already booked"}, status_code=409)

    approvals = {user_id: True}
    if await _admin_can_manage_doctor(user, doctor):
        approvals[str(appt.get("doctor_id"))] = True

    await db.appointments.update_one(
        {"_id": appt_oid},
        {
            "$set": {
                "start_at": start_at,
                "end_at": end_at,
                "mode": str(payload.get("mode") or appt.get("mode") or "online").strip().lower(),
                "status": "change_requested",
                "approvals": approvals,
                "change_requested_by": user_id,
                "updated_at": datetime.utcnow(),
            }
        },
    )
    updated = await db.appointments.find_one({"_id": appt_oid})
    return JSONResponse({"appointment": _appointment_json(updated, user_id)})


@router.post("/api/appointments/{appointment_id}/reject")
async def api_reject_appointment(request: Request, appointment_id: str):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    db = get_database()
    user_id = str(user.get("_id"))
    try:
        appt_oid = ObjectId(appointment_id)
    except Exception:
        return JSONResponse({"error": "Invalid appointment"}, status_code=400)

    appt = await db.appointments.find_one({"_id": appt_oid})
    if not appt:
        return JSONResponse({"error": "Appointment not found"}, status_code=404)

    doctor = await db.users.find_one({"_id": ObjectId(str(appt.get("doctor_id")))})
    allowed = user_id in {str(appt.get("doctor_id")), str(appt.get("patient_id"))}
    if not allowed and not (await _admin_can_manage_doctor(user, doctor)):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    if (appt.get("status") or "pending") == "booked":
        return JSONResponse({"error": "Booked appointments cannot be rejected"}, status_code=409)

    await db.appointments.update_one(
        {"_id": appt_oid},
        {
            "$set": {
                "status": "rejected",
                "rejected_by": user_id,
                "updated_at": datetime.utcnow(),
            }
        },
    )

    conversation_id = str(appt.get("conversation_id") or "")
    if conversation_id:
        await _insert_system_message(db, conversation_id, user_id, "Appointment has been cancelled")

    updated = await db.appointments.find_one({"_id": appt_oid})
    try:
        role = str(user.get("role") or "").strip().lower()
        if _is_admin_user(user):
            cause = "cancelled by admin"
        elif role == "doctor":
            cause = "cancelled by doctor"
        else:
            cause = "cancelled by patient"
        asyncio.create_task(
            _notify_appointment_cancelled(
                db,
                updated or appt,
                cancelled_by=user,
                cause=cause,
            )
        )
    except Exception:
        pass
    return JSONResponse({"appointment": _appointment_json(updated, user_id)})


@router.post("/api/appointments/{appointment_id}/delete")
async def api_delete_appointment(request: Request, appointment_id: str):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if not _is_physihome_info_admin(user):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    db = get_database()
    try:
        appt_oid = ObjectId(appointment_id)
    except Exception:
        return JSONResponse({"error": "Invalid appointment"}, status_code=400)

    appt = await db.appointments.find_one({"_id": appt_oid})
    if not appt:
        return JSONResponse({"error": "Appointment not found"}, status_code=404)

    conversation_id = str(appt.get("conversation_id") or "")
    now = datetime.utcnow()

    try:
        asyncio.create_task(
            _notify_appointment_cancelled(
                db,
                appt,
                cancelled_by=user,
                cause="cancelled by admin",
            )
        )
    except Exception:
        pass

    await db.appointments.delete_one({"_id": appt_oid})

    if conversation_id:
        await db.messages.insert_one(
            {
                "conversation_id": conversation_id,
                "sender_id": str(user.get("_id")),
                "ciphertext": _encrypt_text("Appointment has been deleted by SuperAdmin"),
                "created_at": now,
            }
        )
        try:
            await db.conversations.update_one({"_id": ObjectId(conversation_id)}, {"$set": {"updated_at": now}})
        except Exception:
            pass

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

    now = _utcnow_ms()
    await db.messages.insert_one(
        {
            "conversation_id": str(convo_oid),
            "sender_id": user_id,
            "ciphertext": _encrypt_text(message),
            "created_at": now,
        }
    )
    await db.conversations.update_one({"_id": convo_oid}, {"$set": {"updated_at": now}})
    await _maybe_notify_whatsapp_new_message(db, convo, user, user_id)
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
    if not _is_admin_user(user):
        return RedirectResponse(url="/profile", status_code=303)

    db = get_database()
    users = await db.users.find().to_list(length=200)
    super_admin = _is_super_admin_user(user)

    users_list = []
    doctors_verified = []
    pending_verification = []
    admin_profiles = []

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
            "assigned_admin_id": record.get("assigned_admin_id"),
            "assigned_admin_name": record.get("assigned_admin_name"),
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

        if _is_admin_user(record):
            admin_profiles.append(
                {
                    "_id": str(record.get("_id")),
                    "name": _user_display_name(record),
                    "email": record.get("email"),
                }
            )

    return templates.TemplateResponse(
        "dashboard/admin.html",
        await build_context(
            request,
            users=users_list,
            doctors=doctors_verified,
            pending=pending_verification,
            admins=sorted(admin_profiles, key=lambda item: ((item.get("name") or "").lower(), (item.get("email") or "").lower())),
            is_super_admin=super_admin,
        ),
    )


@router.get("/admin/calendar", response_class=HTMLResponse)
async def admin_calendar(request: Request, admin_id: str | None = Query(None), doctor_id: str | None = Query(None)):
    user = await get_user_from_request(request)
    if not user or not _is_admin_user(user):
        return RedirectResponse(url="/login", status_code=303)

    db = get_database()
    viewer_admin_id = str(user.get("_id"))
    target_admin_id = viewer_admin_id
    if admin_id and _is_super_admin_user(user):
        target_admin_id = str(admin_id)
    doctors = await db.users.find(
        {"role": "doctor", "doctor_verification_status": "verified", "assigned_admin_id": target_admin_id},
        {"first_name": 1, "last_name": 1, "email": 1, "phone": 1, "specialization": 1},
    ).sort("first_name", 1).to_list(length=100)
    unassigned_count = await db.users.count_documents(
        {
            "role": "doctor",
            "doctor_verification_status": "verified",
            "$or": [{"assigned_admin_id": {"$exists": False}}, {"assigned_admin_id": None}, {"assigned_admin_id": ""}],
        }
    )
    return templates.TemplateResponse(
        "dashboard/calendar.html",
        await build_context(
            request,
            doctors=[
                {
                    "_id": str(d.get("_id")),
                    "name": _user_display_name(d),
                    "email": d.get("email"),
                    "phone": d.get("phone"),
                    "specialization": d.get("specialization") or "General",
                }
                for d in doctors
            ],
            unassigned_count=unassigned_count,
            initial_doctor_id=str(doctor_id or ""),
            calendar_admin_id=str(target_admin_id or ""),
        ),
    )


@router.get("/api/admin/calendar")
async def api_admin_calendar(request: Request, doctor_id: str | None = Query(None), admin_id: str | None = Query(None)):
    user = await get_user_from_request(request)
    if not user or not _is_admin_user(user):
        return JSONResponse({"error": "Unauthorized"}, status_code=403)

    db = get_database()
    viewer_admin_id = str(user.get("_id"))
    target_admin_id = viewer_admin_id
    if admin_id and _is_super_admin_user(user):
        target_admin_id = str(admin_id)

    query = {"assigned_admin_id": target_admin_id, "role": "doctor"}
    if doctor_id:
        try:
            query["_id"] = ObjectId(doctor_id)
        except Exception:
            return JSONResponse({"error": "Invalid doctor"}, status_code=400)
    doctors = await db.users.find(query, {"first_name": 1, "last_name": 1}).to_list(length=100)
    doctor_ids = [str(d.get("_id")) for d in doctors]
    appointments = []
    if doctor_ids:
        await _auto_cancel_appointments(db, {"doctor_id": {"$in": doctor_ids}})
        appointments = await db.appointments.find(
            {"doctor_id": {"$in": doctor_ids}, "status": {"$in": ["pending", "booked", "change_requested"]}}
        ).sort("start_at", 1).to_list(length=200)
    return JSONResponse(
        {
            "doctors": [{"_id": str(d.get("_id")), "name": _user_display_name(d)} for d in doctors],
            "appointments": [_appointment_json(a, viewer_admin_id) for a in appointments],
            "can_delete_appointments": _is_physihome_info_admin(user),
            "admin_id": target_admin_id,
        }
    )


@router.post("/api/admin/doctors/{doctor_id}/assign")
async def api_assign_doctor_to_admin(request: Request, doctor_id: str):
    user = await get_user_from_request(request)
    if not user or not _is_admin_user(user):
        return JSONResponse({"error": "Unauthorized"}, status_code=403)

    db = get_database()
    try:
        doctor_oid = ObjectId(doctor_id)
    except Exception:
        return JSONResponse({"error": "Invalid doctor"}, status_code=400)
    doctor = await db.users.find_one({"_id": doctor_oid, "role": "doctor"})
    if not doctor:
        return JSONResponse({"error": "Doctor not found"}, status_code=404)

    assigned = doctor.get("assigned_admin_id")
    if assigned and str(assigned) != str(user.get("_id")):
        return JSONResponse({"error": "This doctor is assigned to another admin"}, status_code=403)

    await db.users.update_one(
        {"_id": doctor_oid},
        {"$set": {"assigned_admin_id": str(user.get("_id")), "assigned_admin_name": _user_display_name(user)}},
    )
    return JSONResponse({"ok": True})


@router.post("/api/admin/doctors/{doctor_id}/assign-to")
async def api_assign_doctor_to_selected_admin(
    request: Request,
    doctor_id: str,
    admin_id: str = Form(""),
):
    user = await get_user_from_request(request)
    if not user or not _is_admin_user(user):
        return JSONResponse({"error": "Unauthorized"}, status_code=403)
    if not _is_super_admin_user(user):
        return JSONResponse({"error": "Only info@physihome.shop can assign doctors to other admins"}, status_code=403)

    db = get_database()
    try:
        doctor_oid = ObjectId(doctor_id)
        admin_oid = ObjectId(str(admin_id))
    except Exception:
        return JSONResponse({"error": "Invalid doctor or admin"}, status_code=400)

    doctor = await db.users.find_one({"_id": doctor_oid, "role": "doctor"})
    admin = await db.users.find_one({"_id": admin_oid})
    if not doctor:
        return JSONResponse({"error": "Doctor not found"}, status_code=404)
    if not _is_admin_user(admin):
        return JSONResponse({"error": "Admin not found"}, status_code=404)

    await db.users.update_one(
        {"_id": doctor_oid},
        {"$set": {"assigned_admin_id": str(admin.get("_id")), "assigned_admin_name": _user_display_name(admin)}},
    )
    return JSONResponse({"ok": True, "assigned_admin_id": str(admin.get("_id")), "assigned_admin_name": _user_display_name(admin)})


@router.get("/api/admin/admins/{admin_id}/doctors")
async def api_admin_assigned_doctors(request: Request, admin_id: str):
    user = await get_user_from_request(request)
    if not user or not _is_admin_user(user):
        return JSONResponse({"error": "Unauthorized"}, status_code=403)
    if not _is_super_admin_user(user):
        return JSONResponse({"error": "Only info@physihome.shop can view admin doctor assignments"}, status_code=403)

    db = get_database()
    try:
        admin_oid = ObjectId(admin_id)
    except Exception:
        return JSONResponse({"error": "Invalid admin"}, status_code=400)

    admin = await db.users.find_one({"_id": admin_oid})
    if not _is_admin_user(admin):
        return JSONResponse({"error": "Admin not found"}, status_code=404)

    doctors = await db.users.find(
        {"role": "doctor", "assigned_admin_id": str(admin_oid)},
        {"first_name": 1, "last_name": 1, "email": 1, "specialization": 1},
    ).sort("first_name", 1).to_list(length=200)
    return JSONResponse(
        {
            "doctors": [
                {
                    "_id": str(d.get("_id")),
                    "name": _user_display_name(d),
                    "email": d.get("email"),
                    "specialization": d.get("specialization") or "General",
                }
                for d in doctors
            ]
        }
    )


@router.post("/api/admin/admins/{admin_id}/doctors/{doctor_id}/remove")
async def api_remove_doctor_from_admin(request: Request, admin_id: str, doctor_id: str):
    user = await get_user_from_request(request)
    if not user or not _is_admin_user(user):
        return JSONResponse({"error": "Unauthorized"}, status_code=403)
    if not _is_super_admin_user(user):
        return JSONResponse({"error": "Only info@physihome.shop can update admin doctor assignments"}, status_code=403)

    db = get_database()
    try:
        doctor_oid = ObjectId(doctor_id)
    except Exception:
        return JSONResponse({"error": "Invalid doctor"}, status_code=400)

    doctor = await db.users.find_one({"_id": doctor_oid, "role": "doctor"})
    if not doctor:
        return JSONResponse({"error": "Doctor not found"}, status_code=404)
    if str(doctor.get("assigned_admin_id") or "") != str(admin_id):
        return JSONResponse({"error": "Doctor is not assigned to this admin"}, status_code=400)

    await db.users.update_one(
        {"_id": doctor_oid},
        {"$set": {"assigned_admin_id": "", "assigned_admin_name": ""}},
    )
    return JSONResponse({"ok": True})


@router.post("/api/admin/cleanup-admin-chats")
async def api_cleanup_admin_chats(request: Request):
    user = await get_user_from_request(request)
    if not user or not _is_admin_user(user):
        return JSONResponse({"error": "Unauthorized"}, status_code=403)

    db = get_database()
    admin_ids = await _get_admin_ids(db)
    if not admin_ids:
        return JSONResponse({"ok": True, "merged": 0, "deleted": 0})

    convos = []
    cursor = db.conversations.find({}).sort("updated_at", -1)
    async for convo in cursor:
        participants = [str(pid) for pid in (convo.get("participants") or [])]
        if len(participants) < 2:
            continue
        non_admin = [pid for pid in participants if pid not in admin_ids]
        if len(non_admin) != 1:
            continue
        if not all(pid in admin_ids for pid in participants if pid != non_admin[0]):
            continue
        convos.append((non_admin[0], convo))

    groups: dict[str, list[dict]] = {}
    for owner_id, convo in convos:
        groups.setdefault(owner_id, []).append(convo)

    merged = 0
    deleted = 0
    for owner_id, items in groups.items():
        if len(items) <= 1:
            continue

        def _updated_at(c: dict):
            return c.get("updated_at") or c.get("created_at")

        items_sorted = sorted(items, key=_updated_at, reverse=True)
        keep = items_sorted[0]
        keep_id = str(keep.get("_id"))
        if not keep_id:
            continue

        for dupe in items_sorted[1:]:
            dupe_id = str(dupe.get("_id"))
            if not dupe_id or dupe_id == keep_id:
                continue

            await db.messages.update_many(
                {"conversation_id": dupe_id},
                {"$set": {"conversation_id": keep_id}},
            )
            await db.conversations.delete_one({"_id": dupe.get("_id")})
            deleted += 1
            merged += 1

        await db.conversations.update_one(
            {"_id": keep.get("_id")},
            {"$set": {"updated_at": datetime.utcnow()}},
        )

    return JSONResponse({"ok": True, "merged": merged, "deleted": deleted})
