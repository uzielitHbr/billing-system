from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.dtos.auth_dto import LoginRequestDTO, LoginResponseDTO, LoginUserDTO
from app.repositories.oracle_pool import (
    oracle_transaction,
    sp_registrar_bitacora,
    sp_sincronizar_usuario_cognito,
)
from app.security.cognito_client import authenticate_user
from app.security.jwt_validator import InactiveUserError, validate_cognito_id_token


def login(
    dto: LoginRequestDTO,
    client_ip: str,
    config: Mapping[str, Any] | None = None,
) -> LoginResponseDTO:
    """Authenticate against Cognito, verify IdToken, and sync/audit user in Oracle."""
    auth_result = authenticate_user(
        email=str(dto.email),
        password=dto.password,
        config=config,
    )
    id_token = auth_result["id_token"]
    expires_in = auth_result["expires_in"]

    claims = validate_cognito_id_token(id_token, config=config)
    cognito_sub = str(claims.get("sub", "")).strip()
    email = str(claims.get("email") or dto.email).strip()
    name = str(claims.get("name") or email).strip()

    with oracle_transaction(config=config) as conn:
        user_sync = sp_sincronizar_usuario_cognito(
            conn,
            cognito_sub=cognito_sub,
            email=email,
            nombre=name,
        )
        if user_sync.get("activo") != 1:
            raise InactiveUserError("Usuario inactivo")

        sp_registrar_bitacora(
            conn,
            id_factura=None,
            accion="LOGIN",
            descripcion=f"Inicio de sesión exitoso: {email}",
            ip_origen=client_ip,
            usuario=email,
        )

    return LoginResponseDTO(
        token=id_token,
        expiresIn=expires_in,
        user=LoginUserDTO(
            id=user_sync["id_usuario"],
            cognitoSub=cognito_sub,
            email=email,
            name=name,
            role=user_sync["rol"],
        ),
    )
