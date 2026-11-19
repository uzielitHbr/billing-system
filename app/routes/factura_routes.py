from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from app.dtos.base import format_pydantic_error
from app.dtos.factura_dto import (
    CancelarFacturaRequestDTO,
    CrearFacturaRequestDTO,
    ValidarProductosRequestDTO,
)
from app.repositories.oracle_pool import (
    InvoiceNotFoundError,
    InvoiceStateConflictError,
)
from app.security.jwt_validator import require_auth
from app.services import export_service, factura_service
from app.services.factura_service import ProductosValidationError

factura_bp = Blueprint("facturas", __name__)


def _parse_json_dto(dto_cls):
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


@factura_bp.post("/facturas/validar")
@require_auth
def validar_productos_endpoint():
    """Validate SKUs against DynamoDB ListServices and compute official totals."""
    dto, err_resp = _parse_json_dto(ValidarProductosRequestDTO)
    if err_resp is not None:
        return err_resp

    try:
        res_dto = factura_service.validar_productos(dto, config=current_app.config)
    except ProductosValidationError as exc:
        return jsonify(exc.payload.model_dump()), 422

    return jsonify(res_dto.model_dump()), 200


@factura_bp.post("/facturas")
@require_auth
def crear_factura_endpoint():
    """Revalidate DynamoDB prices and create draft invoice atomically in Oracle."""
    dto, err_resp = _parse_json_dto(CrearFacturaRequestDTO)
    if err_resp is not None:
        return err_resp

    try:
        res_dto = factura_service.crear_factura(
            dto=dto,
            current_user=g.current_user,
            client_ip=g.client_ip,
            config=current_app.config,
        )
    except ProductosValidationError as exc:
        return jsonify(exc.payload.model_dump()), 422

    return jsonify(res_dto.model_dump()), 201


@factura_bp.get("/facturas/<int:id_factura>")
@require_auth
def obtener_factura_endpoint(id_factura: int):
    """Return full invoice detail from Oracle."""
    try:
        res_dto = factura_service.obtener_factura(
            id_factura=id_factura,
            config=current_app.config,
        )
    except InvoiceNotFoundError as exc:
        return jsonify({"error": "NOT_FOUND", "mensaje": exc.message}), 404

    return jsonify(res_dto.model_dump()), 200


@factura_bp.post("/facturas/<int:id_factura>/emitir")
@require_auth
def emitir_factura_endpoint(id_factura: int):
    """Stamp a PENDIENTE invoice with UUIDv4 and return complete detail."""
    try:
        res_dto = factura_service.emitir_factura(
            id_factura=id_factura,
            current_user=g.current_user,
            client_ip=g.client_ip,
            config=current_app.config,
        )
    except InvoiceNotFoundError as exc:
        return jsonify({"error": "NOT_FOUND", "mensaje": exc.message}), 404
    except InvoiceStateConflictError as exc:
        return jsonify({"error": "CONFLICT", "mensaje": exc.message}), 409

    return jsonify(res_dto.model_dump()), 200


@factura_bp.post("/facturas/<int:id_factura>/cancelar")
@require_auth
def cancelar_factura_endpoint(id_factura: int):
    """Cancel a TIMBRADA invoice with audited reason."""
    dto, err_resp = _parse_json_dto(CancelarFacturaRequestDTO)
    if err_resp is not None:
        return err_resp

    try:
        result = factura_service.cancelar_factura(
            id_factura=id_factura,
            dto=dto,
            current_user=g.current_user,
            client_ip=g.client_ip,
            config=current_app.config,
        )
    except InvoiceNotFoundError as exc:
        return jsonify({"error": "NOT_FOUND", "mensaje": exc.message}), 404
    except InvoiceStateConflictError as exc:
        return jsonify({"error": "CONFLICT", "mensaje": exc.message}), 409

    return jsonify(result), 200


@factura_bp.get("/facturas/<int:id_factura>/exportar")
@require_auth
def exportar_factura_endpoint(id_factura: int):
    """Export invoice as PDF or XML to private S3 and return a 300s pre-signed URL."""
    formato = (request.args.get("formato") or "").strip().lower()
    if formato not in ("pdf", "xml"):
        return (
            jsonify(
                {
                    "error": "BAD_REQUEST",
                    "mensaje": "El parámetro 'formato' es obligatorio y debe ser 'pdf' o 'xml'.",
                }
            ),
            400,
        )

    try:
        result = export_service.exportar_factura(
            id_factura=id_factura,
            formato=formato,
            current_user=g.current_user,
            client_ip=g.client_ip,
            config=current_app.config,
        )
    except InvoiceNotFoundError as exc:
        return jsonify({"error": "NOT_FOUND", "mensaje": exc.message}), 404

    return jsonify(result), 200
