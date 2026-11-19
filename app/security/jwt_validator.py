from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping
from functools import wraps
from typing import Any

import jwt
from flask import current_app, g, jsonify, request
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientError

from app.repositories.oracle_pool import (
    oracle_transaction,
    sp_sincronizar_usuario_cognito,
)


class JWTValidationError(Exception):
    """Raised when a Cognito JWT fails cryptographic or claim validation."""

    def __init__(self, message: str = "Token inválido o expirado") -> None:
        super().__init__(message)
        self.message = message


class InactiveUserError(Exception):
    """Raised when an authenticated user is disabled in Oracle."""

    def __init__(self, message: str = "Usuario inactivo") -> None:
        super().__init__(message)
        self.message = message


_jwk_clients: dict[str, PyJWKClient] = {}
_jwk_lock = threading.Lock()


def _read_setting(key: str, config: Mapping[str, Any] | None, default: str = "") -> str:
    if config and config.get(key):
        return str(config[key]).strip()
    return os.getenv(key, default).strip()


def build_cognito_issuer(region: str, user_pool_id: str) -> str:
    return f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"


def build_cognito_jwks_url(region: str, user_pool_id: str) -> str:
    return f"{build_cognito_issuer(region, user_pool_id)}/.well-known/jwks.json"


def get_jwk_client(region: str, user_pool_id: str) -> PyJWKClient:
    """Return a cached PyJWKClient instance for the Cognito User Pool JWKS endpoint."""
    jwks_url = build_cognito_jwks_url(region, user_pool_id)
    with _jwk_lock:
        client = _jwk_clients.get(jwks_url)
        if client is None:
            client = PyJWKClient(
                jwks_url,
                cache_keys=True,
                lifespan=3600,
                timeout=5,
            )
            _jwk_clients[jwks_url] = client
        return client


def clear_jwk_client_cache() -> None:
    """Clear cached PyJWKClient instances (intended for unit tests)."""
    with _jwk_lock:
        _jwk_clients.clear()


def validate_cognito_id_token(
    token: str,
    config: Mapping[str, Any] | None = None,
    jwk_client: PyJWKClient | None = None,
) -> dict[str, Any]:
    """Verify Cognito IdToken using RS256, JWKS, audience, issuer, and token_use='id'."""
    region = _read_setting("AWS_REGION", config, "us-east-1")
    user_pool_id = _read_setting("COGNITO_USER_POOL_ID", config)
    client_id = _read_setting("COGNITO_CLIENT_ID", config)

    if not user_pool_id or not client_id:
        raise JWTValidationError("Configuración de Cognito incompleta")

    try:
        header = jwt.get_unverified_header(token)
    except InvalidTokenError as exc:
        raise JWTValidationError("Token JWT malformado") from exc

    if header.get("alg") != "RS256":
        raise JWTValidationError("Algoritmo JWT no permitido")

    issuer = build_cognito_issuer(region, user_pool_id)
    resolved_jwk_client = jwk_client or get_jwk_client(region, user_pool_id)

    try:
        signing_key = resolved_jwk_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=issuer,
            options={"require": ["exp", "iat", "sub", "token_use"]},
        )
    except (InvalidTokenError, PyJWKClientError) as exc:
        raise JWTValidationError("Token inválido o expirado") from exc

    if claims.get("token_use") != "id":
        raise JWTValidationError("El token debe ser un IdToken válido")

    return claims


def get_client_ip() -> str:
    """Extract originating client IP honoring X-Forwarded-For from Nginx."""
    forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded_for:
        first_ip = forwarded_for.split(",")[0].strip()
        if first_ip:
            return first_ip[:45]

    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip[:45]

    return (request.remote_addr or "0.0.0.0")[:45]


def _extract_bearer_token() -> str:
    auth_header = request.headers.get("Authorization", "").strip()
    if not auth_header:
        raise JWTValidationError("Token de autenticación requerido")

    parts = auth_header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise JWTValidationError("Formato de encabezado Authorization inválido")

    return parts[1].strip()


def require_auth(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Validate Bearer IdToken (RS256) and active user in Oracle, setting g.current_user."""

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            token = _extract_bearer_token()
            claims = validate_cognito_id_token(token, config=current_app.config)
        except JWTValidationError:
            return (
                jsonify({"error": "UNAUTHORIZED", "mensaje": "Token inválido o ausente"}),
                401,
            )

        sub = str(claims.get("sub", "")).strip()
        email = str(claims.get("email", "")).strip()
        name = str(claims.get("name") or email or sub).strip()

        with oracle_transaction(config=current_app.config) as conn:
            user_sync = sp_sincronizar_usuario_cognito(
                conn,
                cognito_sub=sub,
                email=email,
                nombre=name,
            )

        if user_sync.get("activo") != 1:
            return (
                jsonify({"error": "FORBIDDEN", "mensaje": "Usuario inactivo"}),
                403,
            )

        g.current_user = {
            "id": user_sync["id_usuario"],
            "cognitoSub": sub,
            "email": email,
            "name": name,
            "role": user_sync["rol"],
        }
        g.client_ip = get_client_ip()
        return fn(*args, **kwargs)

    return wrapper
