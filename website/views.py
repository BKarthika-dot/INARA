from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="website/templates")


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse(
        "home.html",
        {"request": request}
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {"request": request}
    )


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    error = request.query_params.get("error")

    error_message = None
    if error == "email":
        error_message = "This email is already registered."
    elif error == "username":
        error_message = "This username is already taken."

    return templates.TemplateResponse(
        "signup.html",
        {
            "request": request,
            "error": error_message
        }
    )



@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request}
    )
