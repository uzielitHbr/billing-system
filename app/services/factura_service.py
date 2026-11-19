from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.dtos.factura_dto import (
    CancelarFacturaRequestDTO,
    ClaveDescripcionDTO,
    ConceptoFacturaDTO,
    CrearFacturaRequestDTO,
    ErrorRenglonDTO,
    ErrorValidacion422DTO,
    FacturaCreadaResponseDTO,
    FacturaDetalleResponseDTO,
    ItemValidadoDTO,
    ProductoItemInputDTO,
    ReceptorFacturaDTO,
    ValidacionTotalesResponseDTO,
    ValidarProductosRequestDTO,
)
from app.repositories.dynamo_repo import get_service_by_sku
from app.repositories.oracle_pool import (
    InvoiceNotFoundError,
    oracle_transaction,
    sp_agregar_detalle_factura,
    sp_cancelar_factura,
    sp_consultar_factura_completa,
    sp_crear_factura_borrador,
    sp_recalcular_totales_factura,
    sp_registrar_bitacora,
    sp_timbrar_factura,
    sp_upsert_cliente,
)

logger = logging.getLogger(__name__)
IVA_RATE = Decimal("0.16")
TWO_PLACES = Decimal("0.01")


def _round_money(amount: Decimal) -> Decimal:
    return amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


class ProductosValidationError(Exception):
    """Raised when one or more SKUs do not exist in DynamoDB ListServices (HTTP 422)."""

    def __init__(self, payload: ErrorValidacion422DTO) -> None:
        super().__init__(payload.mensaje)
        self.payload = payload


@dataclass(frozen=True)
class _PricedLine:
    renglon: int
    sku: str
    nombre: str
    cantidad: int
    precio_decimal: Decimal
    importe_decimal: Decimal


def _validate_and_price_items(
    productos: list[ProductoItemInputDTO],
    config: Mapping[str, Any] | None = None,
) -> tuple[list[_PricedLine], Decimal, Decimal, Decimal]:
    """Resolve authoritative prices from DynamoDB O(1) and calculate IVA 16%."""
    priced_lines: list[_PricedLine] = []
    errores: list[ErrorRenglonDTO] = []

    subtotal = Decimal("0.00")
    impuestos = Decimal("0.00")

    for idx, item in enumerate(productos, start=1):
        service = get_service_by_sku(item.sku, config=config)
        if service is None:
            errores.append(
                ErrorRenglonDTO(
                    renglon=idx,
                    sku=item.sku,
                    mensaje=f"El SKU {item.sku} no existe en ListServices.",
                )
            )
            continue

        precio_unitario = _round_money(Decimal(str(service["precio_unitario"])))
        importe = _round_money(precio_unitario * Decimal(item.cantidad))
        iva_linea = _round_money(importe * IVA_RATE)

        subtotal += importe
        impuestos += iva_linea

        priced_lines.append(
            _PricedLine(
                renglon=idx,
                sku=item.sku,
                nombre=str(service.get("nombre_servicio") or item.sku),
                cantidad=item.cantidad,
                precio_decimal=precio_unitario,
                importe_decimal=importe,
            )
        )

    if errores:
        raise ProductosValidationError(
            ErrorValidacion422DTO(
                mensaje="Uno o más servicios no existen en el catálogo.",
                errores=errores,
            )
        )

    subtotal = _round_money(subtotal)
    impuestos = _round_money(impuestos)
    total = _round_money(subtotal + impuestos)
    return priced_lines, subtotal, impuestos, total


def validar_productos(
    dto: ValidarProductosRequestDTO,
    config: Mapping[str, Any] | None = None,
) -> ValidacionTotalesResponseDTO:
    """Validate requested SKUs against DynamoDB ListServices and compute official totals."""
    lines, subtotal, impuestos, total = _validate_and_price_items(
        dto.productos, config=config
    )

    items_validados = [
        ItemValidadoDTO(
            renglon=line.renglon,
            sku=line.sku,
            nombre=line.nombre,
            cantidad=line.cantidad,
            precioUnitario=float(line.precio_decimal),
            importe=float(line.importe_decimal),
        )
        for line in lines
    ]

    return ValidacionTotalesResponseDTO(
        subtotal=float(subtotal),
        impuestos=float(impuestos),
        total=float(total),
        itemsValidados=items_validados,
    )


def crear_factura(
    dto: CrearFacturaRequestDTO,
    current_user: Mapping[str, Any],
    client_ip: str,
    config: Mapping[str, Any] | None = None,
) -> FacturaCreadaResponseDTO:
    """Revalidate prices in DynamoDB and create draft invoice atomically in Oracle."""
    lines, _, _, _ = _validate_and_price_items(dto.productos, config=config)

    user_id = int(current_user["id"])
    user_email = str(current_user["email"])

    with oracle_transaction(config=config) as conn:
        id_cliente = sp_upsert_cliente(
            conn,
            rfc=dto.rfcReceptor,
            razon_social=dto.razonSocial,
            cp=dto.codigoPostal,
            regimen=dto.regimenFiscal,
            uso_cfdi=dto.usoCfdi,
            email=str(dto.emailReceptor),
        )

        borrador = sp_crear_factura_borrador(
            conn,
            rfc_emisor=dto.rfcEmisor,
            id_cliente=id_cliente,
            id_usuario=user_id,
            forma_pago=dto.formaPago,
            metodo_pago=dto.metodoPago,
            direccion=dto.direccion,
            comentarios=dto.comentarios,
        )
        id_factura = borrador["id_factura"]
        folio = borrador["folio"]

        for line in lines:
            sp_agregar_detalle_factura(
                conn,
                id_factura=id_factura,
                id_servicio_dynamo=line.sku,
                descripcion=line.nombre,
                cantidad=line.cantidad,
                precio_unitario=line.precio_decimal,
            )

        totales = sp_recalcular_totales_factura(conn, id_factura=id_factura)

        sp_registrar_bitacora(
            conn,
            id_factura=id_factura,
            accion="CREACION_BORRADOR",
            descripcion=f"Factura borrador A-{folio} creada",
            ip_origen=client_ip,
            usuario=user_email,
        )

    return FacturaCreadaResponseDTO(
        id=id_factura,
        folio=folio,
        serie="A",
        estado="PENDIENTE",
        subtotal=totales["subtotal"],
        impuestos=totales["impuestos"],
        total=totales["total"],
    )


def _format_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def map_factura_to_dto(raw: Mapping[str, Any]) -> FacturaDetalleResponseDTO:
    """Map SP_CONSULTAR_FACTURA_COMPLETA cursors to FacturaDetalleResponseDTO."""
    cab = raw["cabecera"]
    detalles = raw.get("detalles") or []

    conceptos = [
        ConceptoFacturaDTO(
            sku=str(det["sku"]),
            descripcion=str(det["descripcion_item"]),
            claveSatProducto=str(det.get("clave_sat_producto") or "81112100"),
            claveSatUnidad=str(det.get("clave_sat_unidad") or "E48"),
            cantidad=float(det["cantidad"]),
            precioUnitario=float(det["precio_unitario"]),
            importe=float(det["importe"]),
            iva=float(det.get("importe_iva") or 0),
        )
        for det in detalles
    ]

    return FacturaDetalleResponseDTO(
        id=int(cab["id_factura"]),
        folio=int(cab["folio"]),
        serie=str(cab["serie"]),
        uuid=str(cab["folio_fiscal_uuid"]) if cab.get("folio_fiscal_uuid") else None,
        fechaEmision=_format_timestamp(cab.get("fecha_emision")) or "",
        fechaTimbrado=_format_timestamp(cab.get("fecha_timbrado")),
        estado=str(cab["estado"]),
        rfcEmisor=str(cab["rfc_emisor"]),
        direccion=str(cab["direccion_fiscal"]),
        formaPago=ClaveDescripcionDTO(
            clave=str(cab["id_forma_pago"]),
            descripcion=str(cab["forma_pago_descripcion"]),
        ),
        metodoPago=ClaveDescripcionDTO(
            clave=str(cab["id_metodo_pago"]),
            descripcion=str(cab["metodo_pago_descripcion"]),
        ),
        receptor=ReceptorFacturaDTO(
            rfc=str(cab["rfc_receptor"]),
            razonSocial=str(cab["razon_social"]),
            codigoPostal=str(cab["codigo_postal"]),
            email=str(cab["email_receptor"]),
            regimenFiscal=str(cab["id_regimen_fiscal"]),
            usoCfdi=str(cab["id_uso_cfdi"]),
        ),
        conceptos=conceptos,
        subtotal=float(cab["subtotal"]),
        impuestos=float(cab["total_impuestos"]),
        total=float(cab["total"]),
        moneda=str(cab.get("moneda") or "MXN"),
        comentarios=str(cab["comentarios"]) if cab.get("comentarios") is not None else None,
    )


def obtener_factura(
    id_factura: int,
    config: Mapping[str, Any] | None = None,
) -> FacturaDetalleResponseDTO:
    """Retrieve complete invoice detail from Oracle or raise InvoiceNotFoundError."""
    with oracle_transaction(config=config) as conn:
        raw = sp_consultar_factura_completa(conn, id_factura=id_factura)

    if raw is None:
        raise InvoiceNotFoundError("Factura no encontrada.", ora_code=20004)

    return map_factura_to_dto(raw)


def emitir_factura(
    id_factura: int,
    current_user: Mapping[str, Any],
    client_ip: str,
    config: Mapping[str, Any] | None = None,
) -> FacturaDetalleResponseDTO:
    """Stamp a PENDIENTE invoice with a generated UUIDv4 and return full detail."""
    t0 = time.monotonic()
    fiscal_uuid = str(uuid.uuid4())
    user_email = str(current_user["email"])
    logger.info(
        "[emitir] id_factura=%s step=start usuario=%s uuid=%s",
        id_factura,
        user_email,
        fiscal_uuid,
    )

    with oracle_transaction(config=config) as conn:
        logger.info("[emitir] id_factura=%s step=sp_timbrar_factura", id_factura)
        timbrado = sp_timbrar_factura(conn, id_factura=id_factura, uuid=fiscal_uuid)

        logger.info("[emitir] id_factura=%s step=sp_registrar_bitacora", id_factura)
        sp_registrar_bitacora(
            conn,
            id_factura=id_factura,
            accion="TIMBRADO",
            descripcion=(
                f"Factura {timbrado['serie']}-{timbrado['folio']} "
                f"timbrada con UUID {fiscal_uuid}"
            ),
            ip_origen=client_ip,
            usuario=user_email,
        )

        logger.info("[emitir] id_factura=%s step=sp_consultar_factura_completa", id_factura)
        raw = sp_consultar_factura_completa(conn, id_factura=id_factura)

    if raw is None:
        raise InvoiceNotFoundError("Factura no encontrada.", ora_code=20004)

    dto = map_factura_to_dto(raw)
    logger.info(
        "[emitir] id_factura=%s step=done elapsed_ms=%.1f",
        id_factura,
        (time.monotonic() - t0) * 1000,
    )
    return dto


def cancelar_factura(
    id_factura: int,
    dto: CancelarFacturaRequestDTO,
    current_user: Mapping[str, Any],
    client_ip: str,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Cancel a TIMBRADA invoice with audited reason via SP_CANCELAR_FACTURA."""
    user_email = str(current_user["email"])

    with oracle_transaction(config=config) as conn:
        sp_cancelar_factura(
            conn,
            id_factura=id_factura,
            motivo=dto.motivo,
            usuario=user_email,
            ip_origen=client_ip,
        )

    return {"id": id_factura, "estado": "CANCELADA"}
