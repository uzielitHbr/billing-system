from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from werkzeug.exceptions import BadRequest

from app import create_app
from app.config import Settings

FRONTEND_ORIGIN = "http://billing-frontend-utez.s3-website-us-east-1.amazonaws.com"


@pytest.fixture()
def client():
    app = create_app(
        test_config={
            "TESTING": True,
            "CORS_ALLOWED_ORIGINS": [FRONTEND_ORIGIN, "http://localhost:5173"],
        }
    )
    return app.test_client()


def test_health_returns_200_and_flask_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    data = response.get_json()
    assert data == {
        "status": "ok",
        "service": "billing-system-backend",
        "checks": {
            "flask": "ok",
            "oracle": "not_configured",
            "dynamodb": "not_configured",
        },
    }


def test_health_cors_headers_for_s3_frontend(client):
    response = client.get("/health", headers={"Origin": FRONTEND_ORIGIN})

    assert response.status_code == 200
    assert response.headers.get("Access-Control-Allow-Origin") == FRONTEND_ORIGIN


def test_health_cors_preflight_for_s3_frontend(client):
    response = client.options(
        "/health",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code in (200, 204)
    assert response.headers.get("Access-Control-Allow-Origin") == FRONTEND_ORIGIN


def test_health_cors_blocks_unlisted_origin(client):
    response = client.get("/health", headers={"Origin": "http://evil.example.com"})

    assert response.status_code == 200
    assert response.headers.get("Access-Control-Allow-Origin") is None


def test_health_optional_dependency_checks_without_ora_leak():
    def failing_oracle():
        raise RuntimeError("ORA-12154: TNS:could not resolve the connect identifier")

    app = create_app(
        test_config={
            "TESTING": True,
            "HEALTH_CHECKS": {
                "oracle": failing_oracle,
                "dynamodb": lambda: True,
            },
        }
    )
    test_client = app.test_client()

    response = test_client.get("/health")
    assert response.status_code == 503
    data = response.get_json()
    assert data["status"] == "degraded"
    assert data["checks"]["flask"] == "ok"
    assert data["checks"]["oracle"] == "error"
    assert data["checks"]["dynamodb"] == "ok"
    assert "ORA-" not in response.get_data(as_text=True)


def test_error_handlers_return_clean_json_and_hide_internal_errors():
    app = create_app(test_config={"TESTING": False})

    @app.get("/_test_ora_500")
    def trigger_500():
        raise RuntimeError("ORA-00942: table or view does not exist")

    @app.get("/_test_ora_400")
    def trigger_400():
        raise BadRequest("ORA-01400: cannot insert NULL")

    test_client = app.test_client()

    resp_404 = test_client.get("/ruta-inexistente")
    assert resp_404.status_code == 404
    assert resp_404.get_json()["error"] == "NOT_FOUND"

    resp_500 = test_client.get("/_test_ora_500")
    assert resp_500.status_code == 500
    assert resp_500.get_json() == {
        "error": "INTERNAL_SERVER_ERROR",
        "mensaje": "Error interno del servidor",
    }
    assert "ORA-" not in resp_500.get_data(as_text=True)

    resp_400 = test_client.get("/_test_ora_400")
    assert resp_400.status_code == 400
    assert resp_400.get_json() == {
        "error": "BAD_REQUEST",
        "mensaje": "Solicitud inválida",
    }
    assert "ORA-" not in resp_400.get_data(as_text=True)


def test_production_config_requires_all_env_vars(monkeypatch):
    for var in (
        "AWS_REGION",
        "COGNITO_USER_POOL_ID",
        "COGNITO_CLIENT_ID",
        "DYNAMO_TABLE_SERVICES",
        "S3_BUCKET_COMPROBANTES",
        "ORACLE_USER",
        "ORACLE_PASSWORD",
        "ORACLE_DSN",
        "CORS_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("FLASK_ENV", "production")

    with pytest.raises(ValueError, match="Faltan variables de entorno requeridas en producción"):
        Settings.from_env(load_env_file=False)
