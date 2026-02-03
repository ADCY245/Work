import base64
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.db import get_database
from app.services.auth_utils import get_user_from_request

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()
settings = get_settings()


def base_context(request: Request, **extra):
    context = {
        "request": request,
        "current_year": datetime.utcnow().year,
        "is_authenticated": extra.pop("is_authenticated", False),
        "show_messages": extra.pop("show_messages", False),
        "show_admin": extra.pop("show_admin", False),
        "current_user": extra.pop("current_user", None),
    }
    context.update(extra)
    return context


async def build_context(request: Request, **extra):
    user = await get_user_from_request(request)
    is_authenticated = user is not None
    show_admin = bool(user and user.get("is_admin"))
    show_messages = is_authenticated and user and user.get("role") in {"user", "doctor"}
    return base_context(
        request,
        is_authenticated=is_authenticated,
        show_admin=show_admin,
        show_messages=show_messages,
        current_user=user,
        **extra,
    )


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
async def doctors(request: Request):
    db = get_database()
    cursor = db.users.find(
        {"role": "doctor", "doctor_verification_status": "verified"},
        {"first_name": 1, "last_name": 1, "specialization": 1},
    )
    doctors_list = []
    async for doc in cursor:
        doctors_list.append(
            {
                "name": f"Dr. {doc['first_name']} {doc['last_name']}",
                "specialization": doc.get("specialization", "General"),
                "distance": "TBD",
                "availability": "TBD",
            }
        )
    return templates.TemplateResponse(
        "doctors.html", await build_context(request, doctors=doctors_list)
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
async def profile(request: Request, pending_verification: bool = Query(False)):
    user = await get_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    profile_data = {
        "name": f"{user['first_name']} {user['last_name']}",
        "age": "N/A",
        "contact": user["phone"],
        "email": user["email"],
        "role": user["role"],
        "specialization": user.get("specialization"),
        "pending_verification": pending_verification,
        "documents": user.get("documents"),
    }

    def to_data_uri(payload):
        if not payload:
            return None
        encoded = base64.b64encode(payload.get("data", b"")).decode("utf-8")
        return f"data:{payload.get('content_type')};base64,{encoded}"

    return templates.TemplateResponse(
        "profile.html",
        await build_context(
            request,
            profile=profile_data,
            pending_verification=pending_verification,
            self_photo_url=to_data_uri(self_photo),
            degree_photo_url=to_data_uri(degree_photo),
        ),
    )


@router.get("/messages", response_class=HTMLResponse)
async def messages(request: Request):
    sample_threads = [
        {
            "doctor": "Dr. Meera S.",
            "last_message": "See you at 6 PM.",
            "timestamp": "Today - 4:05 PM",
        },
        {
            "doctor": "Dr. Prakash Rao",
            "last_message": "Please continue the stretches.",
            "timestamp": "Yesterday - 8:50 PM",
        },
    ]
    return templates.TemplateResponse(
        "messages.html", await build_context(request, threads=sample_threads)
    )


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    user = await get_user_from_request(request)
    if not user or not user.get("is_admin"):
        return RedirectResponse(url="/login", status_code=303)

    db = get_database()
    users = await db.users.find().to_list(length=200)

    users_list = []
    doctors_verified = []
    pending_verification = []

    def to_data_uri(payload):
        if not payload:
            return None
        encoded = base64.b64encode(payload.get("data", b"")).decode("utf-8")
        return f"data:{payload.get('content_type')};base64,{encoded}"

    for record in users:
        profile = {
            "name": f"{record.get('first_name', '')} {record.get('last_name', '')}".strip(),
            "email": record.get("email"),
            "phone": record.get("phone"),
            "role": "admin" if record.get("is_admin") else record.get("role"),
            "doctor_verification_status": record.get("doctor_verification_status"),
            "self_photo_url": None,
            "degree_photo_url": None,
        }

        documents = record.get("documents", {})
        profile["self_photo_url"] = to_data_uri(documents.get("self_photo"))
        profile["degree_photo_url"] = to_data_uri(documents.get("degree_photo"))

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
