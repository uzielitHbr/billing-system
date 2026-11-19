from __future__ import annotations

from pydantic import EmailStr, Field

from app.dtos.base import StrictDTO


class LoginRequestDTO(StrictDTO):
    """Input schema for POST /auth/login."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginUserDTO(StrictDTO):
    """Authenticated user profile returned inside LoginResponseDTO."""

    id: int = Field(..., ge=1)
    cognitoSub: str = Field(..., min_length=1)
    email: EmailStr
    name: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1)


class LoginResponseDTO(StrictDTO):
    """Output schema for POST /auth/login."""

    token: str = Field(..., min_length=1)
    expiresIn: int = Field(..., ge=1)
    user: LoginUserDTO


class ForgotPasswordRequestDTO(StrictDTO):
    """Input schema for POST /auth/forgot-password."""

    email: EmailStr


class ConfirmForgotPasswordRequestDTO(StrictDTO):
    """Input schema for POST /auth/confirm-forgot-password."""

    email: EmailStr
    code: str = Field(..., min_length=4, max_length=20)
    newPassword: str = Field(..., min_length=8, max_length=128)


class AuthMessageResponseDTO(StrictDTO):
    """Output message schema for password recovery endpoints."""

    mensaje: str
