from __future__ import annotations

from collections.abc import Callable
from flask import Blueprint, current_app, jsonify

from app.repositories.dynamo_repo import check_dynamo_connection
from app.repositories.oracle_pool import check_oracle_connection

health_bp = Blueprint("health", __name__)

_OPTIONAL_DEPENDENCIES = ("oracle", "dynamodb")


def _resolve_health_checks() -> dict[str, Callable[[], bool]]:
    """Return configured health checks or default Oracle/DynamoDB probes."""
    configured = current_app.config.get("HEALTH_CHECKS")
    if configured is not None:
        return configured

    if current_app.config.get("TESTING"):
        return {}

    config = current_app.config
    return {
        "oracle": lambda: check_oracle_connection(config),
        "dynamodb": lambda: check_dynamo_connection(config),
    }


def _run_dependency_check(name: str, check_fn: Callable[[], bool] | None) -> str:
    """Execute an optional dependency health check without exposing internal errors."""
    if check_fn is None:
        return "not_configured"

    try:
        return "ok" if bool(check_fn()) else "error"
    except Exception:
        current_app.logger.exception("Health check failed for dependency: %s", name)
        return "error"


@health_bp.get("/health")
def health_check():
    """Return Flask health status and Oracle/DynamoDB dependency checks."""
    configured_checks = _resolve_health_checks()

    checks: dict[str, str] = {"flask": "ok"}
    has_failure = False

    for dep in _OPTIONAL_DEPENDENCIES:
        status = _run_dependency_check(dep, configured_checks.get(dep))
        checks[dep] = status
        if status == "error":
            has_failure = True

    http_status = 503 if has_failure else 200
    payload = {
        "status": "degraded" if has_failure else "ok",
        "service": "billing-system-backend",
        "checks": checks,
    }
    return jsonify(payload), http_status
