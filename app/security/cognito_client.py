from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import boto3
from botocore.exceptions import ClientError


class CognitoAuthError(Exception):
    """Base authentication error returned by Amazon Cognito."""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class InvalidCredentialsError(CognitoAuthError):
    """Generic 401 error preventing user enumeration."""

    def __init__(self, message: str = "Credenciales inválidas") -> None:
        super().__init__(message, status_code=401)


class PasswordChangeRequiredError(CognitoAuthError):
    """403 error when Cognito requires confirming a permanent password."""

    def __init__(
        self,
        message: str = "La contraseña del usuario debe confirmarse como permanente.",
    ) -> None:
        super().__init__(message, status_code=403)


def _read_setting(key: str, config: Mapping[str, Any] | None, default: str = "") -> str:
    if config and config.get(key):
        return str(config[key]).strip()
    return os.getenv(key, default).strip()


def authenticate_user(
    email: str,
    password: str,
    config: Mapping[str, Any] | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Authenticate user with Amazon Cognito USER_PASSWORD_AUTH flow."""
    region = _read_setting("AWS_REGION", config, "us-east-1")
    client_id = _read_setting("COGNITO_CLIENT_ID", config)

    if not client_id:
        raise RuntimeError("COGNITO_CLIENT_ID no configurado")

    idp_client = client or boto3.client("cognito-idp", region_name=region)

    try:
        response = idp_client.initiate_auth(
            ClientId=client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": email,
                "PASSWORD": password,
            },
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("NotAuthorizedException", "UserNotFoundException"):
            raise InvalidCredentialsError("Credenciales inválidas") from exc
        if error_code in ("PasswordResetRequiredException", "UserNotConfirmedException"):
            raise PasswordChangeRequiredError(
                "El usuario requiere confirmación o cambio de contraseña en Cognito."
            ) from exc
        raise

    if response.get("ChallengeName") == "NEW_PASSWORD_REQUIRED":
        raise PasswordChangeRequiredError(
            "La contraseña del usuario debe confirmarse como permanente."
        )

    auth_result = response.get("AuthenticationResult") or {}
    id_token = auth_result.get("IdToken")
    if not id_token:
        raise InvalidCredentialsError("Credenciales inválidas")

    return {
        "id_token": str(id_token),
        "expires_in": int(auth_result.get("ExpiresIn", 3600)),
    }
