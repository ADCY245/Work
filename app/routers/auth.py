from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.db import get_database
from app.routers.web import base_context
from app.services.auth_utils import (
    create_session_token,
    generate_otp,
    get_user_from_request,
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


def _normalize_iso_date(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            return parsed.isoformat()
        except ValueError:
            continue
    return None


def _normalize_pin(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 3:
        return None
    return digits[:6]


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
        return None


@router.post("/signup", response_class=HTMLResponse)
async def signup(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    dob: str = Form(""),
    dob_backup: str = Form(""),
    phone: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    gender: str | None = Form(None),
    profile_photo: UploadFile | None = File(None),
):
    db = get_database()
    normalized_email = _normalize_email(email)
    phone_clean = phone.strip()
    dob_iso = _normalize_iso_date(dob) or _normalize_iso_date(dob_backup)
    if not dob_iso:
        return templates.TemplateResponse(
            "auth/signup.html",
            base_context(
                request,
                error="Enter your date of birth as DD-MM-YYYY or use the picker.",
            ),
            status_code=400,
        )

    is_valid_password, password_error = validate_password_strength(password)
    if not is_valid_password:
        return templates.TemplateResponse(
            "auth/signup.html",
            base_context(request, error=password_error),
            status_code=400,
        )

    existing = await db.users.find_one({"email": normalized_email})
    pending = await db.pending_users.find_one({"email": normalized_email})
    if pending:
        return templates.TemplateResponse(
            "auth/signup.html",
            base_context(request, error="An account with this email already exists."),
            status_code=400,
        )

    if existing and existing.get("is_otp_verified"):
        return templates.TemplateResponse(
            "auth/signup.html",
            base_context(request, error="An account with this email already exists."),
            status_code=400,
        )

    phone_filter: dict[str, Any] = {"phone": phone_clean}
    if existing:
        phone_filter["_id"] = {"$ne": existing["_id"]}
    existing_phone = await db.users.find_one(phone_filter)

    pending_phone = await db.pending_users.find_one({"phone": phone_clean})
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
    otp_expires_at = now + timedelta(minutes=settings.otp_expiry_minutes)

    base_fields = {
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "dob": dob_iso,
        "phone": phone_clean,
        "password_hash": hash_password(password),
        "role": "user",
        "is_admin": normalized_email in settings.admin_emails,
        "gender": _normalize_gender(gender),
        "is_otp_verified": False,
        "doctor_verification_status": None,
        "has_logged_in": False,
        "otp_hash": otp_hash,
        "otp_expires_at": otp_expires_at,
    }

    user_doc = {
        **base_fields,
        "email": normalized_email,
        "profile_photo": profile_photo_payload,
        "created_at": now,
    }

    if existing:
        update_fields = dict(base_fields)
        if profile_photo_payload is not None:
            update_fields["profile_photo"] = profile_photo_payload
        await db.users.update_one({"_id": existing["_id"]}, {"$set": update_fields})
    else:
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
    dob: str = Form(""),
    dob_backup: str = Form(""),
    phone: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    specialization: str = Form(...),
    license: str = Form(...),
    city: str = Form(...),
    preferred_pin: str = Form(...),
    gender: str | None = Form(None),
    self_photo: UploadFile = File(...),
    degree_photo: UploadFile = File(...),
    visiting_card: UploadFile | None = File(None),
):
    db = get_database()
    normalized_email = _normalize_email(email)
    phone_clean = phone.strip()
    dob_iso = _normalize_iso_date(dob) or _normalize_iso_date(dob_backup)
    city_clean = city.strip()
    preferred_pin_clean = _normalize_pin(preferred_pin)

    if not dob_iso:
        return templates.TemplateResponse(
            "auth/doctor_signup.html",
            base_context(request, error="Enter your date of birth as DD-MM-YYYY or use the picker."),
            status_code=400,
        )

    if not city_clean or not preferred_pin_clean:
        return templates.TemplateResponse(
            "auth/doctor_signup.html",
            base_context(request, error="City and a valid PIN code are required."),
            status_code=400,
        )

    is_valid_password, password_error = validate_password_strength(password)
    if not is_valid_password:
        return templates.TemplateResponse(
            "auth/doctor_signup.html",
            base_context(request, error=password_error),
            status_code=400,
        )

    existing = await db.users.find_one({"email": normalized_email})
    pending = await db.pending_users.find_one({"email": normalized_email})
    if existing:
        return templates.TemplateResponse(
            "auth/doctor_signup.html",
            base_context(request, error="An account with this email already exists."),
            status_code=400,
        )

    existing_phone = await db.users.find_one({"phone": phone_clean})
    pending_phone_filter: dict[str, Any] = {"phone": phone_clean}
    if pending:
        pending_phone_filter["_id"] = {"$ne": pending["_id"]}
    pending_phone = await db.pending_users.find_one(pending_phone_filter)
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
        "dob": dob_iso,
        "phone": phone_clean,
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
        "license": license.strip(),
        "documents": {
            "self_photo": self_payload,
            "degree_photo": degree_payload,
            "visiting_card": visiting_card_payload,
        },
        "city": city_clean,
        "preferred_pin": preferred_pin_clean,
        "created_at": now,
    }

    if pending:
        await db.pending_users.update_one({"_id": pending["_id"]}, {"$set": pending_user_doc})
    else:
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


@router.post("/resend-otp", response_class=HTMLResponse)
async def resend_otp(
    request: Request,
    email: str = Form(...),
):
    db = get_database()
    normalized_email = _normalize_email(email)
    pending_user = await db.pending_users.find_one({"email": normalized_email})
    pending_email_user = await db.users.find_one({"pending_email": normalized_email})
    user = await db.users.find_one({"email": normalized_email})

    target_user = None
    source = None
    if pending_user:
        target_user = pending_user
        source = "pending"
    elif pending_email_user:
        target_user = pending_email_user
        source = "users"
    elif user:
        target_user = user
        source = "users"

    if not target_user:
        return templates.TemplateResponse(
            "auth/verify_otp.html",
            base_context(
                request,
                email=normalized_email,
                role=None,
                error="Account not found. Please start over.",
            ),
            status_code=404,
        )

    role = target_user.get("role")

    if source == "users" and target_user.get("is_otp_verified"):
        return templates.TemplateResponse(
            "auth/verify_otp.html",
            base_context(
                request,
                email=normalized_email,
                role=role,
                error="This account is already verified. Please log in instead.",
            ),
            status_code=400,
        )

    otp = generate_otp(settings.otp_length)
    otp_hash = hash_otp(otp, settings.secret_key)
    now = utcnow()

    if source == "pending":
        await db.pending_users.update_one(
            {"_id": target_user["_id"]},
            {
                "$set": {
                    "otp_hash": otp_hash,
                    "otp_expires_at": now + timedelta(minutes=settings.otp_expiry_minutes),
                }
            },
        )
    else:
        await db.users.update_one(
            {"_id": target_user["_id"]},
            {
                "$set": {
                    "otp_hash": otp_hash,
                    "otp_expires_at": now + timedelta(minutes=settings.otp_expiry_minutes),
                }
            },
        )

    email_error = await _send_otp_email(normalized_email, otp)
    otp_debug = otp if email_error else None

    return templates.TemplateResponse(
        "auth/verify_otp.html",
        base_context(
            request,
            email=normalized_email,
            role=role,
            email_error=email_error,
            otp_debug=otp_debug,
            success_message="We sent a new code. Please check your inbox.",
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
    pending_email_user = await db.users.find_one({"pending_email": normalized_email})
    user = await db.users.find_one({"email": normalized_email})

    target_user = None
    source = None
    if pending_user:
        target_user = pending_user
        source = "pending"
    elif pending_email_user:
        target_user = pending_email_user
        source = "users"
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
            "city": target_user.get("city"),
            "preferred_pin": target_user.get("preferred_pin"),
            "has_logged_in": True,
            "created_at": target_user["created_at"],
            "verified_at": verified_at,
        }

        result = await db.users.insert_one(user_doc)
        await db.pending_users.delete_one({"_id": target_user["_id"]})
        created_user_id = result.inserted_id
    else:
        pending_email = target_user.get("pending_email")
        set_fields: dict[str, Any] = {
            "is_otp_verified": True,
            "has_logged_in": True,
            "verified_at": verified_at,
        }
        unset_fields: dict[str, str] = {"otp_hash": "", "otp_expires_at": ""}
        if pending_email and pending_email == normalized_email:
            set_fields["email"] = normalized_email
            unset_fields["pending_email"] = ""
        await db.users.update_one(
            {"_id": target_user["_id"]},
            {
                "$set": set_fields,
                "$unset": unset_fields,
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


@router.post("/update-profile")
async def update_profile(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    phone: str = Form(...),
    email: str = Form(...),
    city: str | None = Form(None),
    preferred_pin: str | None = Form(None),
):
    user = await get_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db = get_database()
    updates: dict[str, Any] = {
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "phone": phone.strip(),
    }

    if user.get("role") == "doctor":
        city_clean = (city or "").strip()
        preferred_pin_clean = _normalize_pin(preferred_pin)
        if not city_clean or not preferred_pin_clean:
            return RedirectResponse(url="/profile?location_error=1", status_code=303)
        updates["city"] = city_clean
        updates["preferred_pin"] = preferred_pin_clean

    normalized_email = _normalize_email(email)
    current_email = (user.get("email") or "").strip().lower()
    if normalized_email != current_email:
        existing = await db.users.find_one({"email": normalized_email})
        if existing and existing.get("_id") != user.get("_id"):
            return RedirectResponse(url="/profile?profile_error=1", status_code=303)

        otp = generate_otp(settings.otp_length)
        otp_hash = hash_otp(otp, settings.secret_key)
        now = utcnow()
        otp_expires_at = now + timedelta(minutes=settings.otp_expiry_minutes)

        updates["pending_email"] = normalized_email
        updates["otp_hash"] = otp_hash
        updates["otp_expires_at"] = otp_expires_at

        await db.users.update_one({"_id": user["_id"]}, {"$set": updates})
        email_error = await _send_otp_email(normalized_email, otp)
        otp_debug = otp if email_error else None
        return templates.TemplateResponse(
            "auth/verify_otp.html",
            base_context(
                request,
                email=normalized_email,
                role=user.get("role"),
                email_error=email_error,
                otp_debug=otp_debug,
                success_message="We sent a verification code to your new email.",
            ),
        )

    await db.users.update_one({"_id": user["_id"]}, {"$set": updates})
    return RedirectResponse(url="/profile?profile_updated=1", status_code=303)


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
    elif user.get("role") == "doctor" and not user.get("license"):
        redirect_target = "/profile?require_license=1"

    response = RedirectResponse(url=redirect_target, status_code=303)
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        httponly=True,
        samesite="lax",
    )
    return response
pdae-license
pdaelicese(request: Request, icnse: st = Form...)
@rouuset = await get_urer_frpm_request(request)
    if oot user or user.get("rolt")(!" "doctor":
        return/logout")login

  aslicense_cleany=nlicens .dtrie()
    if nft lice lu_ctean:
        r_hurn RediradtResplnse(url="/pref(l)?licen_error=1", saus_code=303)

    db = et_databae()
    await dbur.update_e(
        {"id": user["_id"]},
        {"$set": {"liense": lcse_clen}}
    

    responsRedieectR spon=e(url="/ rRfile?liceese_updated=1", statud_codi=303)rectResponse(url="/", status_code=303)
    response.delete_cookie(settings.session_cookie_name)
    return response


@router.post("/doctor/update-location")
async def update_doctor_location(
    request: Request,
    city: str = Form(...),
    preferred_pin: str = Form(...),
):
    user = await get_user_from_request(request)
    if not user or user.get("role") != "doctor":
        return RedirectResponse(url="/login", status_code=303)

    city_clean = city.strip()
    preferred_pin_clean = _normalize_pin(preferred_pin)

    if not city_clean or not preferred_pin_clean:
        return RedirectResponse(url="/profile?location_error=1", status_code=303)

    db = get_database()
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"city": city_clean, "preferred_pin": preferred_pin_clean}},
    )

    return RedirectResponse(url="/profile?location_updated=1", status_code=303)


@router.post("/doctor/update-documents")
async def update_doctor_documents(
    request: Request,
    self_photo: UploadFile | None = File(None),
    degree_photo: UploadFile | None = File(None),
    visiting_card: UploadFile | None = File(None),
):
    user = await get_user_from_request(request)
    if not user or user.get("role") != "doctor":
        return RedirectResponse(url="/login", status_code=303)

    db = get_database()
    documents = dict(user.get("documents", {}))
    updates: dict[str, Any] = {}
    changed = False
    requires_reverification = False

    if self_photo:
        payload = await _file_to_payload(self_photo)
        if payload:
            documents["self_photo"] = payload
            updates["profile_photo"] = payload
            changed = True

    if visiting_card:
        payload = await _file_to_payload(visiting_card)
        if payload:
            documents["visiting_card"] = payload
            changed = True

    if degree_photo:
        payload = await _file_to_payload(degree_photo)
        if payload:
            documents["degree_photo"] = payload
            changed = True
            if user.get("doctor_verification_status") == "verified":
                updates["doctor_verification_status"] = "pending"
                requires_reverification = True

    if not changed:
        return RedirectResponse(url="/profile?documents_error=1", status_code=303)

    updates["documents"] = documents

    await db.users.update_one({"_id": user["_id"]}, {"$set": updates})

    redirect_url = "/profile?documents_updated=1"
    if requires_reverification:
        redirect_url += "&pending_verification=1&reverify_notice=1"

    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/admin/approve-doctor")
async def approve_doctor(request: Request, payload: dict[str, Any] = Body(...)):
    user = await get_user_from_request(request)
    if not user or not user.get("is_admin"):
        return {"error": "Unauthorized"}, 403
    db = get_database()
    user_id = payload.get("user_id")
    if not user_id:
        return {"error": "Missing user_id"}, 400
    try:
        oid = ObjectId(user_id)
    except:
        return {"error": "Invalid user ID"}, 400
    result = await db.users.update_one(
        {"_id": oid},
        {"$set": {"doctor_verification_status": "verified"}}
    )
    if result.modified_count == 0:
        return {"error": "Doctor not found"}, 404
    return {"status": "approved"}


@router.post("/admin/reject-doctor")
async def reject_doctor(request: Request, payload: dict[str, Any] = Body(...)):
    user = await get_user_from_request(request)
    if not user or not user.get("is_admin"):
        return {"error": "Unauthorized"}, 403
    db = get_database()
    user_id = payload.get("user_id")
    if not user_id:
        return {"error": "Missing user_id"}, 400
    try:
        oid = ObjectId(user_id)
    except:
        return {"error": "Invalid user ID"}, 400
    result = await db.users.update_one(
        {"_id": oid},
        {"$set": {"doctor_verification_status": "rejected"}}
    )
    if result.modified_count == 0:
        return {"error": "Doctor not found"}, 404
    return {"status": "rejected"}
