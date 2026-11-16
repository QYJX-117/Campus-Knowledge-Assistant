from pydantic import BaseModel, EmailStr, Field


class RegisterBody(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)


class LoginBody(BaseModel):
    email: EmailStr
    password: str
    captcha_token: str = ""
    captcha_answer: str = ""


class UserResponse(BaseModel):
    id: int; name: str; email: str; role: str; is_active: bool; created_at: str


class AuthResponse(BaseModel):
    token: str; user: UserResponse
