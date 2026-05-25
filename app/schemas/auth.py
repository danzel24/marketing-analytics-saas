from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
  email: EmailStr
  password: str = Field(..., min_length=8, max_length=128)
  client_name: str = Field(..., min_length=2, max_length=64)


class LoginIn(BaseModel):
  email: EmailStr
  password: str = Field(..., min_length=8, max_length=128)
  remember_me: bool = False


class TokenOut(BaseModel):
  access_token: str
  token_type: str = "bearer"


class ForgotPasswordIn(BaseModel):
  email: EmailStr


class ResetPasswordIn(BaseModel):
  token: str = Field(..., min_length=1, max_length=256)
  new_password: str = Field(..., min_length=8, max_length=128)

