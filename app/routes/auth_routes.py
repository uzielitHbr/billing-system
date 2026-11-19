from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from pydantic import ValidationError

from app.dtos.auth_dto import (
    ConfirmForgotPasswordRequestDTO,
    ForgotPasswordRequestDTO,
    LoginRequestDTO,
)
from app.dtos.base import format_pydantic_error
from app.security.cognito_client import (
    CognitoValidationError,
    InvalidCredentialsError,
    PasswordChangeRequiredError,
    RateLimitExceededError,
)
from app.security.jwt_validator import InactiveUserError, JWTValidationError, get_client_ip
from app.services import auth_service

auth_bp = Blueprint("auth", __name__)


def _parse_dto(dto_cls):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, (
            jsonify({"error": "BAD_REQUEST", "mensaje": "Cuerpo JSON válido requerido"}),
            400,
        )
    try:
        return dto_cls.model_validate(payload), None
    except ValidationError as exc:
        return None, (jsonify(format_pydantic_error(exc)), 400)


@auth_bp.post("/auth/login")
def login_endpoint():
    """Authenticate user via Amazon Cognito and sync profile in Oracle."""
    dto, err_resp = _parse_dto(LoginRequestDTO)
    if err_resp is not None:
        return err_resp

    try:
        response_dto = auth_service.login(
            dto=dto,
            client_ip=get_client_ip(),
            config=current_app.config,
        )
    except (InvalidCredentialsError, JWTValidationError):
        return (
            jsonify({"error": "UNAUTHORIZED", "mensaje": "Credenciales inválidas"}),
            401,
        )
    except (PasswordChangeRequiredError, InactiveUserError) as exc:
        return jsonify({"error": "FORBIDDEN", "mensaje": exc.message}), 403

    return jsonify(response_dto.model_dump()), 200


@auth_bp.post("/auth/forgot-password")
def forgot_password_endpoint():
    """Public endpoint to start Amazon Cognito password recovery."""
    dto, err_resp = _parse_dto(ForgotPasswordRequestDTO)
    if err_resp is not None:
        return err_resp

    try:
        response_dto = auth_service.forgot_password(dto=dto, config=current_app.config)
    except CognitoValidationError as exc:
        return jsonify({"error": "BAD_REQUEST", "mensaje": exc.message}), 400
    except RateLimitExceededError as exc:
        return jsonify({"error": "TOO_MANY_REQUESTS", "mensaje": exc.message}), 429

    return jsonify(response_dto.model_dump()), 200


@auth_bp.post("/auth/confirm-forgot-password")
def confirm_forgot_password_endpoint():
    """Public endpoint to confirm password reset with Cognito verification code."""
    dto, err_resp = _parse_dto(ConfirmForgotPasswordRequestDTO)
    if err_resp is not None:
        return err_resp

    try:
        response_dto = auth_service.confirm_forgot_password(
            dto=dto,
            config=current_app.config,
        )
    except CognitoValidationError as exc:
        return jsonify({"error": "BAD_REQUEST", "mensaje": exc.message}), 400
    except RateLimitExceededError as exc:
        return jsonify({"error": "TOO_MANY_REQUESTS", "mensaje": exc.message}), 429

    return jsonify(response_dto.model_dump()), 200
