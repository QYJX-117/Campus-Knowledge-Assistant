"""Auth routes."""

from fastapi import APIRouter, Depends, HTTPException
from ..models.auth import RegisterBody, LoginBody
from ..models.common import Result
from ..services.auth_service import AuthService
from ..database import get_db
from ..config import settings
from ..security import create_captcha, verify_captcha
import sqlite3

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/captcha")
def captcha():
    return Result.ok(create_captcha())


@router.post("/register", status_code=201)
def register(body: RegisterBody, db: sqlite3.Connection = Depends(get_db)):
    return Result.ok(AuthService.register(db, body.name, body.email, body.password))


@router.post("/login")
def login(body: LoginBody, db: sqlite3.Connection = Depends(get_db)):
    if settings.captcha_required and not verify_captcha(body.captcha_token, body.captcha_answer):
        raise HTTPException(400, "验证码错误或已过期")
    return Result.ok(AuthService.login(db, body.email, body.password))


@router.post("/guest")
def guest(db: sqlite3.Connection = Depends(get_db)):
    return Result.ok(AuthService.guest_login(db))
