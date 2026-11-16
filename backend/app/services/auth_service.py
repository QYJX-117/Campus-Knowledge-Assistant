"""Authentication service."""

import sqlite3

from ..config import settings
from ..database import utc_now, transaction
from ..security import create_token, create_guest_token, hash_password, verify_password


def public_user(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"], "is_active": bool(row["is_active"]), "created_at": row["created_at"]}


class AuthService:

    @staticmethod
    def seed_admin(db: sqlite3.Connection) -> int:
        row = db.execute("SELECT id FROM users WHERE email=?", ("admin@campus.example",)).fetchone()
        if row:
            return int(row["id"])
        cur = db.execute("INSERT INTO users(name,email,password_hash,role,is_active,created_at) VALUES(?,?,?,?,?,?)",
                         ("系统管理员", "admin@campus.example", hash_password("admin123"), "ADMIN", 1, utc_now()))
        return int(cur.lastrowid)

    @staticmethod
    def register(db: sqlite3.Connection, name: str, email: str, password: str) -> dict:
        from fastapi import HTTPException
        email = email.lower()
        if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(409, "该邮箱已注册")
        cur = db.execute("INSERT INTO users(name,email,password_hash,role,is_active,created_at) VALUES(?,?,?,?,?,?)",
                         (name.strip(), email, hash_password(password), "STUDENT", 1, utc_now()))
        db.commit()
        user = db.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
        return {"token": create_token(user["id"], user["role"]), "user": public_user(user)}

    @staticmethod
    def login(db: sqlite3.Connection, email: str, password: str) -> dict:
        from fastapi import HTTPException
        user = db.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            raise HTTPException(401, "邮箱或密码错误")
        if not user["is_active"]:
            raise HTTPException(403, "账号已停用")
        return {"token": create_token(user["id"], user["role"]), "user": public_user(user)}

    @staticmethod
    def guest_login(db: sqlite3.Connection) -> dict:
        """Guest login — no real account, just a token with synthetic identity."""
        token, guest_id = create_guest_token()
        return {
            "token": token,
            "user": {
                "id": 0, "name": "访客", "email": f"guest-{guest_id[:8]}@session.local",
                "role": "STUDENT", "is_active": True, "created_at": "", "guest_id": guest_id,
            },
        }
