from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.security.jwt_validator import require_auth
from app.services import catalog_service
from app.services.catalog_service import ServiceNotFoundError

catalog_bp = Blueprint("catalog", __name__)


def _parse_positive_int(raw: str | None, default: int, name: str) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"El parámetro '{name}' debe ser un número entero") from exc
    if value < 1:
        raise ValueError(f"El parámetro '{name}' debe ser mayor o igual a 1")
    return value


@catalog_bp.get("/catalogos/sat")
@require_auth
def listar_catalogos_sat():
    """Return active SAT payment forms, methods, tax regimes, and CFDI uses."""
    catalogs = catalog_service.get_sat_catalogs(config=current_app.config)
    return jsonify(catalogs), 200


@catalog_bp.get("/servicios")
@require_auth
def listar_servicios():
    """Return paginated and optionally filtered services from ListServices cache."""
    query = request.args.get("q", "")
    try:
        page = _parse_positive_int(request.args.get("page"), 1, "page")
        limit = _parse_positive_int(request.args.get("limit"), 20, "limit")
    except ValueError as exc:
        return jsonify({"error": "BAD_REQUEST", "mensaje": str(exc)}), 400

    limit = min(limit, 100)
    result = catalog_service.search_services(
        query=query,
        page=page,
        limit=limit,
        config=current_app.config,
    )
    return jsonify(result), 200


@catalog_bp.get("/servicios/<string:service_id>")
@require_auth
def obtener_servicio_detalle(service_id: str):
    """Return O(1) service detail with 50 characteristics grouped into 5 sections."""
    try:
        dto = catalog_service.get_service_detail(
            service_id=service_id,
            config=current_app.config,
        )
    except ServiceNotFoundError:
        return (
            jsonify(
                {
                    "error": "NOT_FOUND",
                    "mensaje": f"Servicio '{service_id}' no encontrado",
                }
            ),
            404,
        )

    return jsonify(dto.model_dump()), 200
