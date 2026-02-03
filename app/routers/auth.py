from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.db import get_database
from app.routers.web import base_context
from app.services.auth_utils import (
    create_session_token,
    generate_otp,
    hash_otp,
    hash_password,
    utcnow,
    validate_password_strength,
    verify_otp,
    verify_password,
)
from app.services.emailer import send_email

settings = get_settings()

router = APIRouter(prefix="/api/auth", tags=["auth"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _normalize_email(email: str) -> str:
    return email.strip().lower()


async def _file_to_payload(upload: UploadFile | None) -> dict[str, Any] | None:
    if upload is None:
        return None
    content = await upload.read()
    if not content:
        return None
    return {
        "filename": upload.filename or "upload",
        "content_type": upload.content_type or "application/octet-stream",
        "data": content,
    }


def _normalize_gender(value: str | None) -> str | None:
    gender = (value or "").strip().lower()
    if gender in {"male", "female", "other"}:
        return gender
    return None


async def _send_otp_email(email: str, otp: str) -> str | None:
    subject = "Your PhysiHome verification code"
    body = f"Your OTP is {otp}. It expires in {settings.otp_expiry_minutes} minutes."
    try:
        await run_in_threadpool(send_email, subject, body, [email])
        return None
    except Exception as exc:  # pragma: no cover - surface in UI
        return str(exc)


async def _send_doctor_documents_email(email: str, attachments: list[tuple[str, bytes, str]]) -> str | None:
    subject = "New doctor verification documents"
    body = (
        "A doctor completed OTP onboarding. Please review the attached documents.\n"
        f"Doctor email: {email}\n"
    )
    try:
        await run_in_threadpool(send_email, subject, body, settings.admin_emails, attachments)
        return None
    except Exception as exc:  # pragma: no cover - surface in UI
        return str(exc)


@router.post("/signup", response_class=HTMLResponse)
async def signup(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    dob: str = Form(...),
    phone: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    gender: str | None = Form(None),
    profile_photo: UploadFile | None = File(None),
):
    db = get_database()
    normalized_email = _normalize_email(email)

    is_valid_password, password_error = validate_password_strength(password)
    if not is_valid_password:
        return templates.TemplateResponse(
            "auth/signup.html",
            base_context(request, error=password_error),
            status_code=400,
        )

    existing = await db.users.find_one({"email": normalized_email})
    pending = await db.pending_users.find_one({"email": normalized_email})
    if existing or pending:
        return templates.TemplateResponse(
            "auth/signup.html",
            base_context(request, error="An account with this email already exists."),
            status_code=400,
        )

    existing_phone = await db.users.find_one({"phone": phone.strip()})
    pending_phone = await db.pending_users.find_one({"phone": phone.strip()})
    if existing_phone or pending_phone:
        return templates.TemplateResponse(
            "auth/signup.html",
            base_context(request, error="An account with this phone number already exists."),
            status_code=400,
        )

    otp = generate_otp(settings.otp_length)
    otp_hash = hash_otp(otp, settings.secret_key)
    now = utcnow()

    profile_photo_payload = await _file_to_payload(profile_photo)

    user_doc = {
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "dob": dob,
        "phone": phone.strip(),
        "email": normalized_email,
        "password_hash": hash_password(password),
        "role": "user",
        "is_admin": normalized_email in settings.admin_emails,
        "gender": _normalize_gender(gender),
        "profile_photo": profile_photo_payload,
        "is_otp_verified": False,
        "doctor_verification_status": None,
        "has_logged_in": False,
        "otp_hash": otp_hash,
        "otp_expires_at": now + timedelta(minutes=settings.otp_expiry_minutes),
        "created_at": now,
    }

    await db.users.insert_one(user_doc)
    email_error = await _send_otp_email(normalized_email, otp)
    otp_debug = otp if email_error else None

    return templates.TemplateResponse(
        "auth/verify_otp.html",
        base_context(
            request,
            email=normalized_email,
            role="user",
            email_error=email_error,
            otp_debug=otp_debug,
        ),
    )


@router.post("/doctor-signup", response_class=HTMLResponse)
async def doctor_signup(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    dob: str = Form(...),
    phone: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    specialization: str = Form(...),
    gender: str | None = Form(None),
    self_photo: UploadFile = File(...),
    degree_photo: UploadFile = File(...),
    visiting_card: UploadFile | None = File(None),
):
    db = get_database()
    normalized_email = _normalize_email(email)

    is_valid_password, password_error = validate_password_strength(password)
    if not is_valid_password:
        return templates.TemplateResponse(
            "auth/doctor_signup.html",
            base_context(request, error=password_error),
            status_code=400,
        )

    existing = await db.users.find_one({"email": normalized_email})
    pending = await db.pending_users.find_one({"email": normalized_email})
    if existing or pending:
        return templates.TemplateResponse(
            "auth/doctor_signup.html",
            base_context(request, error="An account with this email already exists."),
            status_code=400,
        )

    existing_phone = await db.users.find_one({"phone": phone.strip()})
    pending_phone = await db.pending_users.find_one({"phone": phone.strip()})
    if existing_phone or pending_phone:
        return templates.TemplateResponse(
            "auth/doctor_signup.html",
            base_context(request, error="An account with this phone number already exists."),
            status_code=400,
        )

    otp = generate_otp(settings.otp_length)
    otp_hash = hash_otp(otp, settings.secret_key)
    now = utcnow()

    self_payload = await _file_to_payload(self_photo)
    degree_payload = await _file_to_payload(degree_photo)
    visiting_card_payload = await _file_to_payload(visiting_card)

    if not self_payload or not degree_payload:
        return templates.TemplateResponse(
            "auth/doctor_signup.html",
            base_context(request, error="Both self photo and degree certificate are required."),
            status_code=400,
        )

    # Store pending doctor signup in a separate collection until OTP is verified
    pending_user_doc = {
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "dob": dob,
        "phone": phone.strip(),
        "email": normalized_email,
        "password_hash": hash_password(password),
        "role": "doctor",
        "is_admin": normalized_email in settings.admin_emails,
        "gender": _normalize_gender(gender),
        "profile_photo": self_payload,
        "otp_hash": otp_hash,
        "otp_expires_at": now + timedelta(minutes=settings.otp_expiry_minutes),
        "doctor_verification_status": "pending",
        "specialization": specialization.strip(),
        "documents": {
            "self_photo": self_payload,
            "degree_photo": degree_payload,
            "visiting_card": visiting_card_payload,
        },
        "created_at": now,
    }

    await db.pending_users.insert_one(pending_user_doc)

    email_error = await _send_otp_email(normalized_email, otp)
    otp_debug = otp if email_error else None

    attachments = [
        (self_payload["filename"], self_payload["data"], self_payload["content_type"]),
        (degree_payload["filename"], degree_payload["data"], degree_payload["content_type"]),
    ]
    if visiting_card_payload:
        attachments.append(
            (
                visiting_card_payload["filename"],
                visiting_card_payload["data"],
                visiting_card_payload["content_type"],
            )
        )
    admin_email_error = await _send_doctor_documents_email(normalized_email, attachments)

    return templates.TemplateResponse(
        "auth/verify_otp.html",
        base_context(
            request,
            email=normalized_email,
            role="doctor",
            email_error=email_error,
            admin_email_error=admin_email_error,
            otp_debug=otp_debug,
        ),
    )


@router.post("/verify-otp", response_class=HTMLResponse)
async def verify_otp_handler(
    request: Request,
    email: str = Form(...),
    otp: str = Form(...),
):
    db = get_database()
    normalized_email = _normalize_email(email)
    pending_user = await db.pending_users.find_one({"email": normalized_email})
    user = await db.users.find_one({"email": normalized_email})

    target_user = None
    source = None
    if pending_user:
        target_user = pending_user
        source = "pending"
    elif user:
        target_user = user
        source = "users"
    else:
        return templates.TemplateResponse(
            "auth/verify_otp.html",
            base_context(request, error="Account not found. Please sign up again."),
            status_code=404,
        )

    role = target_user.get("role")
    otp_hash = target_user.get("otp_hash")
    otp_expires_at = target_user.get("otp_expires_at")

    if not otp_hash or not otp_expires_at:
        return templates.TemplateResponse(
            "auth/verify_otp.html",
            base_context(
                request,
                email=normalized_email,
                role=role,
                error="OTP not found. Please request a new one.",
            ),
            status_code=400,
        )

    if utcnow() > otp_expires_at:
        return templates.TemplateResponse(
            "auth/verify_otp.html",
            base_context(
                request,
                email=normalized_email,
                role=role,
                error="OTP expired. Please sign up again.",
            ),
            status_code=400,
        )

    if not verify_otp(otp.strip(), otp_hash, settings.secret_key):
        return templates.TemplateResponse(
            "auth/verify_otp.html",
            base_context(
                request,
                email=normalized_email,
                role=role,
                error="Incorrect OTP. Try again.",
            ),
            status_code=400,
        )

    verified_at = utcnow()
    if source == "pending":
        doctor_status = target_user.get("doctor_verification_status")
        user_doc = {
            "first_name": target_user["first_name"],
            "last_name": target_user["last_name"],
            "dob": target_user["dob"],
            "phone": target_user["phone"],
            "email": target_user["email"],
            "password_hash": target_user["password_hash"],
            "role": target_user["role"],
            "is_admin": target_user.get("is_admin", False),
            "gender": target_user.get("gender"),
            "profile_photo": target_user.get("profile_photo"),
            "is_otp_verified": True,
            "doctor_verification_status": doctor_status,
            "specialization": target_user.get("specialization"),
            "documents": target_user.get("documents"),
            "has_logged_in": True,
            "created_at": target_user["created_at"],
            "verified_at": verified_at,
        }

        result = await db.users.insert_one(user_doc)
        await db.pending_users.delete_one({"_id": target_user["_id"]})
        created_user_id = result.inserted_id
    else:
        await db.users.update_one(
            {"_id": target_user["_id"]},
            {
                "$set": {
                    "is_otp_verified": True,
                    "has_logged_in": True,
                    "verified_at": verified_at,
                },
                "$unset": {"otp_hash": "", "otp_expires_at": ""},
            },
        )
        created_user_id = target_user["_id"]
        doctor_status = target_user.get("doctor_verification_status")

    session_token = create_session_token(
        {"user_id": str(created_user_id), "email": normalized_email},
        settings.secret_key,
    )

    redirect_target = "/profile"
    if role == "doctor" and doctor_status != "verified":
        redirect_target = "/profile?pending_verification=1"

    response = RedirectResponse(url=redirect_target, status_code=303)
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/login")
async def login_handler(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    db = get_database()
    normalized_email = _normalize_email(email)
    user = await db.users.find_one({"email": normalized_email})

    if not user or not verify_password(password, user.get("password_hash", "")):
        return templates.TemplateResponse(
            "auth/login.html",
            base_context(request, error="Invalid email or password."),
            status_code=400,
        )

    if not user.get("is_otp_verified"):
        return templates.TemplateResponse(
            "auth/login.html",
            base_context(request, error="Please complete OTP verification before logging in."),
            status_code=400,
        )

    await db.users.update_one({"_id": user["_id"]}, {"$set": {"has_logged_in": True}})

    session_token = create_session_token(
        {"user_id": str(user["_id"]), "email": normalized_email},
        settings.secret_key,
    )

    redirect_target = "/profile"
    if user.get("role") == "doctor" and user.get("doctor_verification_status") != "verified":
        redirect_target = "/profile?pending_verification=1"

    response = RedirectResponse(url=redirect_target, status_code=303)
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout_handler():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(settings.session_cookie_name)
    return response


@router.post("/admin/approve-doctor")
async def approve_doctor(request: Request, payload: dict[str, str]):
    user = await get_user_from_request(request)
    if not user or not user.get("is_admin"):
        return {"error": "Unauthorized"}, 403
    db = get_database()
    user_id = payload.get("user_id")
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"doctor_verification_status": "verified"}}
    )
    return {"status": "approved"}


@router.post("/admin/reject-doctor")
async def reject_doctor(request: Request, payload: dict[str, str]):
    user = await get_user_from_request(request)
    if not user or not user.get("is_admin"):
        return {"error": "Unauthorized"}, 403
    db = get_database()
    user_id = payload.get("user_id")
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"doctor_verification_status": "rejected"}}
    )
    return {"status": "rejected"}
