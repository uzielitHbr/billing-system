from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from pydantic import ValidationError

from app.dtos.auth_dto import LoginRequestDTO
from app.dtos.base import format_pydantic_error
from app.security.cognito_client import (
    InvalidCredentialsError,
    PasswordChangeRequiredError,
)
from app.security.jwt_validator import InactiveUserError, JWTValidationError, get_client_ip
from app.services import auth_service

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/auth/login")
def login_endpoint():
    """Authenticate user via Amazon Cognito and sync profile in Oracle."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return (
            jsonify({"error": "BAD_REQUEST", "mensaje": "Cuerpo JSON válido requerido"}),
            400,
        )

    try:
        dto = LoginRequestDTO.model_validate(payload)
    except ValidationError as exc:
        return jsonify(format_pydantic_error(exc)), 400

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
