from fastapi import APIRouter, Form
from fastapi.responses import RedirectResponse

from .mongodb import users_collection
from .security import hash_password, verify_password, create_access_token

router = APIRouter()


@router.post("/signup")
async def signup(
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...)
):
    # check duplicate email
    if await users_collection.find_one({"email": email}):
        return RedirectResponse("/signup?error=email", status_code=302)

    # check duplicate username
    if await users_collection.find_one({"username": username}):
        return RedirectResponse("/signup?error=username", status_code=302)

    user_doc = {
        "email": email,
        "username": username,
        "password_hash": hash_password(password)
    }

    result = await users_collection.insert_one(user_doc)

    token = create_access_token({"sub": str(result.inserted_id)})

    response = RedirectResponse("/dashboard", status_code=302)
    response.set_cookie("access_token", token, httponly=True)

    return response


@router.post("/login")
async def login(
    username: str = Form(...),
    password: str = Form(...)
):
    user = await users_collection.find_one({"username": username})

    if not user:
        return RedirectResponse("/login?error=user", status_code=302)

    if not verify_password(password, user["password_hash"]):
        return RedirectResponse("/login?error=password", status_code=302)

    token = create_access_token({"sub": str(user["_id"])})

    response = RedirectResponse("/dashboard", status_code=302)
    response.set_cookie("access_token", token, httponly=True)

    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("access_token")
    return response
