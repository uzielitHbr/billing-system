from __future__ import annotations

import re
from typing import Any

from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from app.config import Settings, parse_cors_origins
from app.routes.health_routes import health_bp

_ERROR_CATALOG: dict[int, tuple[str, str]] = {
    400: ("BAD_REQUEST", "Solicitud inválida"),
    401: ("UNAUTHORIZED", "Credenciales inválidas"),
    403: ("FORBIDDEN", "Acceso denegado"),
    404: ("NOT_FOUND", "Recurso no encontrado"),
    409: ("CONFLICT", "Conflicto con el estado del recurso"),
    422: ("UNPROCESSABLE_ENTITY", "Error de validación"),
    500: ("INTERNAL_SERVER_ERROR", "Error interno del servidor"),
}

_INTERNAL_LEAK_PATTERN = re.compile(
    r"(ORA-\d+|PLS-\d+|TNS-\d+|Traceback\s*\(|oracledb|File\s+\")",
    re.IGNORECASE,
)


def _sanitize_error_message(raw_message: str | None, fallback: str) -> str:
    """Return fallback if raw_message contains internal DB errors or stack traces."""
    if not raw_message or "\n" in raw_message:
        return fallback
    if _INTERNAL_LEAK_PATTERN.search(raw_message):
        return fallback
    return raw_message


def _build_error_response(status_code: int, message: str | None = None):
    code, default_message = _ERROR_CATALOG.get(
        status_code, ("HTTP_ERROR", "Error al procesar la solicitud")
    )
    safe_message = (
        default_message
        if status_code >= 500
        else _sanitize_error_message(message, default_message)
    )
    return jsonify({"error": code, "mensaje": safe_message}), status_code


def _register_error_handlers(app: Flask) -> None:
    """Register global JSON error handlers that hide stack traces and ORA- errors."""
    for status_code in _ERROR_CATALOG:

        @app.errorhandler(status_code)
        def handle_http_status(error: Any, code: int = status_code):
            description = getattr(error, "description", None)
            if code >= 500:
                app.logger.exception("Unhandled HTTP %s error: %s", code, error)
                return _build_error_response(code)
            if description and _INTERNAL_LEAK_PATTERN.search(str(description)):
                app.logger.warning(
                    "Suppressed sensitive detail on HTTP %s: %s", code, description
                )
            return _build_error_response(code, description)

    @app.errorhandler(Exception)
    def handle_unexpected_exception(error: Exception):
        if isinstance(error, HTTPException) and error.code is not None:
            if error.code >= 500:
                app.logger.exception("Unhandled HTTPException %s: %s", error.code, error)
                return _build_error_response(error.code)
            return _build_error_response(error.code, error.description)

        app.logger.exception("Unhandled internal exception: %s", error)
        return _build_error_response(500)


def create_app(
    test_config: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> Flask:
    """Application factory for billing-system-backend."""
    app = Flask(__name__)

    loaded_settings = settings or Settings.from_env()
    app.config.from_object(loaded_settings)

    if test_config:
        app.config.update(test_config)

    cors_origins = parse_cors_origins(app.config.get("CORS_ALLOWED_ORIGINS"))
    CORS(app, resources={r"/*": {"origins": cors_origins}})

    _register_error_handlers(app)
    app.register_blueprint(health_bp)

    return app
