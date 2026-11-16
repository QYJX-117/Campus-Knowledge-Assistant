"""User management routes."""

import sqlite3
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from ..services.auth_service import public_user
from ..models.user import ProfileUpdateBody, UserCreateBody, UserUpdateBody
from ..security import hash_password, verify_password
from ..database import utc_now
from ..models.common import Result
from ..database import get_db
from .chat import admin_user, current_user, is_guest_user

router = APIRouter(prefix="/api/users", tags=["users"])


@router.patch("/me")
def update_profile(
    body: ProfileUpdateBody,
    db: sqlite3.Connection = Depends(get_db),
    actor=Depends(current_user),
):
    if is_guest_user(actor):
        raise HTTPException(403, "访客不能修改个人信息")
    if not verify_password(body.current_password, actor["password_hash"]):
        raise HTTPException(400, "当前密码不正确")
    email = str(body.email).strip().lower()
    duplicate = db.execute(
        "SELECT 1 FROM users WHERE email=? AND id<>?", (email, actor["id"]),
    ).fetchone()
    if duplicate:
        raise HTTPException(409, "该邮箱已被其他账号使用")
    name = body.name.strip()
    password_hash = hash_password(body.new_password) if body.new_password else actor["password_hash"]
    db.execute(
        "UPDATE users SET name=?,email=?,password_hash=? WHERE id=?",
        (name, email, password_hash, actor["id"]),
    )
    db.commit()
    return Result.ok(public_user(db.execute("SELECT * FROM users WHERE id=?", (actor["id"],)).fetchone()))


@router.get("")
def list_users(
    page: int | None = Query(None, ge=1),
    size: int | None = Query(None, ge=1, le=100),
    keyword: str = Query("", max_length=80),
    role: str | None = Query(None),
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(admin_user),
):
    conditions = []
    params: list[object] = []
    if keyword.strip():
        conditions.append("(name LIKE ? OR email LIKE ?)")
        like = f"%{keyword.strip()}%"
        params.extend([like, like])
    if role in {"ADMIN", "STUDENT"}:
        conditions.append("role=?")
        params.append(role)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    if page is None and size is None and not conditions:
        rows = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return Result.ok([public_user(r) for r in rows])
    total = db.execute(f"SELECT COUNT(*) FROM users {where}", params).fetchone()[0]
    current_page = page or 1
    page_size = size or 10
    rows = db.execute(
        f"SELECT * FROM users {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        [*params, page_size, (current_page - 1) * page_size],
    ).fetchall()
    return Result.ok({"records": [public_user(r) for r in rows], "total": total, "page": current_page, "size": page_size})


@router.post("", status_code=201)
def create_user(body: UserCreateBody, db: sqlite3.Connection = Depends(get_db), _=Depends(admin_user)):
    if body.role not in {"STUDENT", "ADMIN"}:
        raise HTTPException(400, "角色无效")
    email = str(body.email).lower()
    if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise HTTPException(409, "该邮箱已注册")
    cur = db.execute(
        "INSERT INTO users(name,email,password_hash,role,is_active,created_at) VALUES(?,?,?,?,?,?)",
        (body.name.strip(), email, hash_password(body.password), body.role, 1, utc_now()),
    )
    db.commit()
    return Result.ok(public_user(db.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()))


@router.patch("/{user_id}")
def update_user(user_id: int, body: UserUpdateBody, db: sqlite3.Connection = Depends(get_db), admin: sqlite3.Row = Depends(admin_user)):
    user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(404, "用户不存在")
    if user_id == admin["id"] and body.is_active is False:
        raise HTTPException(400, "不能停用当前管理员")
    if user_id == admin["id"] and body.role and body.role != "ADMIN":
        raise HTTPException(400, "不能降低当前管理员的角色")
    if body.email:
        email = str(body.email).lower()
        duplicate = db.execute("SELECT 1 FROM users WHERE email=? AND id<>?", (email, user_id)).fetchone()
        if duplicate:
            raise HTTPException(409, "该邮箱已注册")
    role = body.role or user["role"]
    if role not in {"STUDENT", "ADMIN"}:
        raise HTTPException(400, "角色无效")
    active = int(body.is_active) if body.is_active is not None else user["is_active"]
    name = body.name.strip() if body.name else user["name"]
    email = str(body.email).lower() if body.email else user["email"]
    db.execute("UPDATE users SET name=?,email=?,role=?,is_active=? WHERE id=?", (name, email, role, active, user_id))
    db.commit()
    updated = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return Result.ok(public_user(updated))
