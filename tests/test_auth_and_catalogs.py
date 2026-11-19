from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import jwt
import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric import rsa

from app import create_app
from app.security.jwt_validator import clear_jwk_client_cache

REGION = "us-east-1"
POOL_ID = "us-east-1_fWBs2LMa3"
CLIENT_ID = "1dhc6l396sgg79cl4qbn8shqn2"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL_ID}"


@pytest.fixture(scope="module")
def rsa_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def _make_id_token(
    private_key,
    *,
    sub: str = "sub-111",
    email: str = "20243ds112@utez.edu.mx",
    name: str = "Uziel Abraham",
    token_use: str = "id",
    exp_offset: int = 3600,
    aud: str = CLIENT_ID,
    iss: str = ISSUER,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "email": email,
        "name": name,
        "token_use": token_use,
        "aud": aud,
        "iss": iss,
        "iat": now,
        "exp": now + exp_offset,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test-kid"})


@pytest.fixture()
def app_client(rsa_keys):
    clear_jwk_client_cache()
    _, public_key = rsa_keys

    mock_jwk_client = MagicMock()
    mock_jwk_client.get_signing_key_from_jwt.return_value = SimpleNamespace(key=public_key)

    app = create_app(
        test_config={
            "TESTING": True,
            "AWS_REGION": REGION,
            "COGNITO_USER_POOL_ID": POOL_ID,
            "COGNITO_CLIENT_ID": CLIENT_ID,
            "CORS_ALLOWED_ORIGINS": [
                "http://billing-frontend-utez.s3-website-us-east-1.amazonaws.com",
                "http://localhost:5173",
            ],
        }
    )

    with patch(
        "app.security.jwt_validator.get_jwk_client",
        return_value=mock_jwk_client,
    ):
        yield app.test_client()

    clear_jwk_client_cache()


@contextmanager
def _fake_tx():
    yield MagicMock()


def test_login_success_returns_200_syncs_oracle_and_audits(app_client, rsa_keys):
    private_key, _ = rsa_keys
    id_token = _make_id_token(private_key)

    mock_idp = MagicMock()
    mock_idp.initiate_auth.return_value = {
        "AuthenticationResult": {"IdToken": id_token, "ExpiresIn": 3600}
    }

    with (
        patch("app.security.cognito_client.boto3.client", return_value=mock_idp),
        patch("app.services.auth_service.oracle_transaction", side_effect=lambda **_: _fake_tx()),
        patch(
            "app.services.auth_service.sp_sincronizar_usuario_cognito",
            return_value={"id_usuario": 1, "rol": "ADMIN_ACADEMICO", "activo": 1},
        ) as sync_sp,
        patch("app.services.auth_service.sp_registrar_bitacora") as bitacora_sp,
    ):
        resp = app_client.post(
            "/auth/login",
            json={"email": "20243ds112@utez.edu.mx", "password": "Uzielito542."},
            headers={"X-Forwarded-For": "189.10.20.30, 10.0.0.1"},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["token"] == id_token
    assert body["expiresIn"] == 3600
    assert body["user"] == {
        "id": 1,
        "cognitoSub": "sub-111",
        "email": "20243ds112@utez.edu.mx",
        "name": "Uziel Abraham",
        "role": "ADMIN_ACADEMICO",
    }
    sync_sp.assert_called_once()
    bitacora_sp.assert_called_once()
    assert bitacora_sp.call_args.kwargs["ip_origen"] == "189.10.20.30"


def test_login_invalid_credentials_returns_generic_401(app_client):
    for err_code in ("NotAuthorizedException", "UserNotFoundException"):
        mock_idp = MagicMock()
        mock_idp.initiate_auth.side_effect = ClientError(
            {"Error": {"Code": err_code, "Message": "Detailed AWS msg"}},
            "InitiateAuth",
        )
        with patch("app.security.cognito_client.boto3.client", return_value=mock_idp):
            resp = app_client.post(
                "/auth/login",
                json={"email": "20243ds112@utez.edu.mx", "password": "WrongPassword1"},
            )
        assert resp.status_code == 401
        assert resp.get_json() == {
            "error": "UNAUTHORIZED",
            "mensaje": "Credenciales inválidas",
        }


def test_login_new_password_required_returns_403_and_extra_field_returns_400(app_client):
    mock_idp = MagicMock()
    mock_idp.initiate_auth.return_value = {"ChallengeName": "NEW_PASSWORD_REQUIRED"}
    with patch("app.security.cognito_client.boto3.client", return_value=mock_idp):
        resp = app_client.post(
            "/auth/login",
            json={"email": "20243ds112@utez.edu.mx", "password": "TempPassword1"},
        )
    assert resp.status_code == 403

    resp_400 = app_client.post(
        "/auth/login",
        json={
            "email": "20243ds112@utez.edu.mx",
            "password": "Password123",
            "role": "ADMIN_ACADEMICO",
        },
    )
    assert resp_400.status_code == 400


def test_protected_routes_reject_missing_non_rs256_and_expired_tokens(app_client, rsa_keys):
    private_key, _ = rsa_keys

    # 1. Missing token
    resp_missing = app_client.get("/catalogos/sat")
    assert resp_missing.status_code == 401

    # 2. Non-RS256 token (HS256)
    hs256_token = jwt.encode(
        {
            "sub": "sub-111",
            "token_use": "id",
            "aud": CLIENT_ID,
            "iss": ISSUER,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        "shared-secret",
        algorithm="HS256",
    )
    resp_hs256 = app_client.get(
        "/catalogos/sat",
        headers={"Authorization": f"Bearer {hs256_token}"},
    )
    assert resp_hs256.status_code == 401

    # 3. Expired RS256 token
    expired_token = _make_id_token(private_key, exp_offset=-60)
    resp_expired = app_client.get(
        "/catalogos/sat",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp_expired.status_code == 401

    # 4. Access token instead of IdToken
    access_token = _make_id_token(private_key, token_use="access")
    resp_access = app_client.get(
        "/catalogos/sat",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp_access.status_code == 401


def test_catalogos_sat_servicios_pagination_search_and_404(app_client, rsa_keys):
    private_key, _ = rsa_keys
    valid_token = _make_id_token(private_key)
    auth_headers = {
        "Authorization": f"Bearer {valid_token}",
        "X-Forwarded-For": "200.1.2.3",
    }

    sample_catalogs = {
        "formasPago": [{"clave": "03", "descripcion": "Transferencia electrónica de fondos"}],
        "metodosPago": [{"clave": "PUE", "descripcion": "Pago en una sola exhibición"}],
        "regimenesFiscales": [
            {"clave": "601", "descripcion": "General de Ley Personas Morales"}
        ],
        "usosCfdi": [{"clave": "G03", "descripcion": "Gastos en general"}],
    }

    sample_services = [
        {
            "id_service": "SRV-001",
            "nombre_servicio": "Alojamiento Cloud",
            "precio_unitario": Decimal("1250.00"),
            "descripcion": "Servidor administrado",
            "caracteristicas": {
                f"caracteristica_{i:02d}": f"Valor {i:02d}" for i in range(1, 51)
            },
        },
        {
            "id_service": "SRV-002",
            "nombre_servicio": "Soporte Oracle",
            "precio_unitario": Decimal("2500.00"),
            "descripcion": "Administración RDS",
            "caracteristicas": {},
        },
        {
            "id_service": "SRV-003",
            "nombre_servicio": "Respaldo S3",
            "precio_unitario": Decimal("800.00"),
            "descripcion": "Backups cifrados",
            "caracteristicas": {},
        },
    ]

    with (
        patch("app.security.jwt_validator.oracle_transaction", side_effect=lambda **_: _fake_tx()),
        patch(
            "app.security.jwt_validator.sp_sincronizar_usuario_cognito",
            return_value={"id_usuario": 1, "rol": "ADMIN_ACADEMICO", "activo": 1},
        ),
        patch("app.services.catalog_service.oracle_transaction", side_effect=lambda **_: _fake_tx()),
        patch("app.services.catalog_service.sp_listar_catalogos_sat", return_value=sample_catalogs),
        patch("app.services.catalog_service.list_all_services", return_value=sample_services),
        patch(
            "app.services.catalog_service.get_service_by_sku",
            side_effect=lambda sku, config=None: (
                sample_services[0] if sku == "SRV-001" else None
            ),
        ),
    ):
        # GET /catalogos/sat
        resp_cat = app_client.get("/catalogos/sat", headers=auth_headers)
        assert resp_cat.status_code == 200
        assert resp_cat.get_json() == sample_catalogs

        # GET /servicios paginated
        resp_srv = app_client.get("/servicios?page=2&limit=2", headers=auth_headers)
        assert resp_srv.status_code == 200
        data_srv = resp_srv.get_json()
        assert data_srv["total"] == 3
        assert data_srv["page"] == 2
        assert data_srv["limit"] == 2
        assert data_srv["totalPages"] == 2
        assert [item["sku"] for item in data_srv["items"]] == ["SRV-003"]

        # GET /servicios filtered by ?q=oracle
        resp_search = app_client.get("/servicios?q=oracle", headers=auth_headers)
        assert resp_search.status_code == 200
        data_search = resp_search.get_json()
        assert data_search["total"] == 1
        assert data_search["items"][0]["sku"] == "SRV-002"

        # GET /servicios/SRV-001 (50 characteristics in 5 sections)
        resp_det = app_client.get("/servicios/SRV-001", headers=auth_headers)
        assert resp_det.status_code == 200
        det_json = resp_det.get_json()
        assert det_json["sku"] == "SRV-001"
        assert len(det_json["secciones"]) == 5
        assert sum(len(sec["atributos"]) for sec in det_json["secciones"]) == 50

        # GET /servicios/SRV-999 -> 404
        resp_404 = app_client.get("/servicios/SRV-999", headers=auth_headers)
        assert resp_404.status_code == 404
        assert resp_404.get_json()["error"] == "NOT_FOUND"
