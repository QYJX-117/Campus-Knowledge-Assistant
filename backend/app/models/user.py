from pydantic import BaseModel, EmailStr, Field


class UserUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=50)
    email: EmailStr | None = None
    role: str | None = None
    is_active: bool | None = None


class UserCreateBody(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)
    role: str = "STUDENT"


class ProfileUpdateBody(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    email: EmailStr
    current_password: str = Field(min_length=6, max_length=72)
    new_password: str | None = Field(default=None, min_length=6, max_length=72)
