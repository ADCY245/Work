from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


def base_context(request: Request, **extra):
    context = {
        "request": request,
        "current_year": datetime.utcnow().year,
        "is_authenticated": extra.pop("is_authenticated", False),
        "show_messages": extra.pop("show_messages", False),
        "show_admin": extra.pop("show_admin", False),
    }
    context.update(extra)
    return context


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse("landing.html", base_context(request))


@router.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse("about.html", base_context(request))


@router.get("/contact", response_class=HTMLResponse)
async def contact(request: Request):
    return templates.TemplateResponse("contact.html", base_context(request))


@router.get("/doctors", response_class=HTMLResponse)
async def doctors(request: Request):
    doctors_sample = [
        {
            "name": "Dr. Meera S.",
            "specialization": "Physiotherapy",
            "distance": "2.1 km",
            "availability": "Today, 5-8 PM",
        },
        {
            "name": "Dr. Prakash Rao",
            "specialization": "Geriatric Care",
            "distance": "4.5 km",
            "availability": "Tomorrow, 9-2 PM",
        },
    ]
    return templates.TemplateResponse(
        "doctors.html", base_context(request, doctors=doctors_sample)
    )


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    return templates.TemplateResponse("auth/login.html", base_context(request))


@router.get("/signup", response_class=HTMLResponse)
async def signup(request: Request):
    return templates.TemplateResponse("auth/signup.html", base_context(request))


@router.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    sample_profile = {
        "name": "Ananya Pillai",
        "age": 42,
        "contact": "••••••6789",
        "email": "hidden@physihome",
        "role": "patient",
        "specialization": None,
    }
    return templates.TemplateResponse(
        "profile.html", base_context(request, profile=sample_profile)
    )


@router.get("/messages", response_class=HTMLResponse)
async def messages(request: Request):
    sample_threads = [
        {
            "doctor": "Dr. Meera S.",
            "last_message": "See you at 6 PM.",
            "timestamp": "Today · 4:05 PM",
        },
        {
            "doctor": "Dr. Prakash Rao",
            "last_message": "Please continue the stretches.",
            "timestamp": "Yesterday · 8:50 PM",
        },
    ]
    return templates.TemplateResponse(
        "messages.html", base_context(request, threads=sample_threads)
    )


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    sample_users = [
        {"name": "Ananya Pillai", "role": "patient"},
        {"name": "Dr. Meera S.", "role": "doctor"},
    ]
    return templates.TemplateResponse(
        "dashboard/admin.html", base_context(request, users=sample_users)
    )
