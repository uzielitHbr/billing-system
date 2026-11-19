from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from pydantic import ValidationError

from app.dtos.auth_dto import LoginRequestDTO, LoginResponseDTO
from app.dtos.base import format_pydantic_error
from app.dtos.factura_dto import (
    CancelarFacturaRequestDTO,
    CrearFacturaRequestDTO,
    ErrorValidacion422DTO,
    FacturaCreadaResponseDTO,
    FacturaDetalleResponseDTO,
    ProductoItemInputDTO,
    ValidacionTotalesResponseDTO,
    ValidarProductosRequestDTO,
)
from app.dtos.servicio_dto import (
    ServicioDetalleResponseDTO,
    ServicioResumenDTO,
    agrupar_caracteristicas,
    build_servicio_detalle,
)


def _valid_crear_factura_payload() -> dict:
    return {
        "rfcEmisor": "UTE980101ABC",
        "rfcReceptor": "XAXX010101000",
        "razonSocial": "Público en General S.A. de C.V.",
        "codigoPostal": "62760",
        "emailReceptor": "cliente@empresa.mx",
        "regimenFiscal": "601",
        "usoCfdi": "G03",
        "formaPago": "03",
        "metodoPago": "PUE",
        "direccion": "Av. Universidad Tecnológica 1, Emiliano Zapata, Mor.",
        "comentarios": "Servicio mensual de infraestructura",
        "productos": [{"sku": "SRV-001", "cantidad": 2}],
    }


def test_rejects_precio_unitario_and_extra_fields():
    with pytest.raises(ValidationError) as exc_info:
        ProductoItemInputDTO(sku="SRV-001", cantidad=2, precioUnitario=1.0)
    formatted = format_pydantic_error(exc_info.value)
    assert formatted["error"] == "BAD_REQUEST"
    assert any(d["campo"] == "precioUnitario" for d in formatted["detalles"])

    payload = _valid_crear_factura_payload()
    payload["productos"] = [{"sku": "SRV-001", "cantidad": 2, "precioUnitario": 0.01}]
    with pytest.raises(ValidationError):
        CrearFacturaRequestDTO.model_validate(payload)

    with pytest.raises(ValidationError):
        ValidarProductosRequestDTO.model_validate(
            {"productos": [{"sku": "SRV-001", "cantidad": 1}], "rolAdmin": True}
        )

    with pytest.raises(ValidationError):
        LoginRequestDTO.model_validate(
            {
                "email": "20243ds112@utez.edu.mx",
                "password": "Password123",
                "role": "ADMIN_ACADEMICO",
            }
        )

    with pytest.raises(ValidationError):
        CancelarFacturaRequestDTO.model_validate(
            {"motivo": "Error de captura en receptor", "extraField": "nope"}
        )


def test_valid_and_invalid_rfc_cp_and_cantidad():
    dto = CrearFacturaRequestDTO.model_validate(_valid_crear_factura_payload())
    assert dto.rfcEmisor == "UTE980101ABC"
    assert dto.rfcReceptor == "XAXX010101000"
    assert dto.metodoPago == "PUE"

    # RFC inválido e intento de SQL injection
    for bad_rfc in ("' OR 1=1 --", "ABC123", "123456789012", "UTE980101AB", "XAXX0101010000"):
        payload = _valid_crear_factura_payload()
        payload["rfcReceptor"] = bad_rfc
        with pytest.raises(ValidationError):
            CrearFacturaRequestDTO.model_validate(payload)

    # CP inválido
    for bad_cp in ("6276", "627601", "6276A", ""):
        payload = _valid_crear_factura_payload()
        payload["codigoPostal"] = bad_cp
        with pytest.raises(ValidationError):
            CrearFacturaRequestDTO.model_validate(payload)

    # metodoPago inválido
    payload = _valid_crear_factura_payload()
    payload["metodoPago"] = "EFECTIVO"
    with pytest.raises(ValidationError):
        CrearFacturaRequestDTO.model_validate(payload)

    # Cantidades <= 0, booleanas o > 9999
    for bad_qty in (0, -1, -99, True, 10000):
        with pytest.raises(ValidationError):
            ProductoItemInputDTO(sku="SRV-001", cantidad=bad_qty)


def test_agrupar_50_caracteristicas_en_5_secciones_exactas():
    caracteristicas = {
        f"caracteristica_{i:02d}": f"Valor {i:02d}" for i in range(1, 51)
    }
    secciones = agrupar_caracteristicas(caracteristicas)

    assert len(secciones) == 5
    expected_specs = [
        ("fiscal_legal", "Fiscal y legal", 12, 1, 12),
        ("identificacion", "Identificación", 10, 13, 22),
        ("comercial", "Comercial", 10, 23, 32),
        ("contractual", "Contractual", 9, 33, 41),
        ("operativa", "Operativa", 9, 42, 50),
    ]

    total_atributos = 0
    for seccion, (expected_id, expected_titulo, count, start, end) in zip(
        secciones, expected_specs
    ):
        assert seccion.id == expected_id
        assert seccion.titulo == expected_titulo
        assert len(seccion.atributos) == count
        assert seccion.atributos[0].clave == f"caracteristica_{start:02d}"
        assert seccion.atributos[-1].clave == f"caracteristica_{end:02d}"
        total_atributos += len(seccion.atributos)

    assert total_atributos == 50

    detalle = build_servicio_detalle(
        {
            "id_service": "SRV-001",
            "nombre_servicio": "Soporte Cloud",
            "precio_unitario": Decimal("1250.00"),
            "descripcion": "Servicio mensual",
            "caracteristicas": caracteristicas,
        }
    )
    assert isinstance(detalle, ServicioDetalleResponseDTO)
    assert detalle.id == "SRV-001"
    assert detalle.sku == "SRV-001"
    assert detalle.precioUnitario == 1250.00
    assert sum(len(s.atributos) for s in detalle.secciones) == 50


def test_output_dtos_match_rest_contracts():
    login_res = LoginResponseDTO(
        token="eyJraWQiOi...",
        expiresIn=3600,
        user={
            "id": 1,
            "cognitoSub": "a1b2c3d4-e5f6",
            "email": "20243ds112@utez.edu.mx",
            "name": "20243ds112@utez.edu.mx",
            "role": "ADMIN_ACADEMICO",
        },
    )
    assert login_res.user.role == "ADMIN_ACADEMICO"

    valid_res = ValidacionTotalesResponseDTO(
        subtotal=2500.00,
        impuestos=400.00,
        total=2900.00,
        itemsValidados=[
            {
                "renglon": 1,
                "sku": "SRV-001",
                "nombre": "Servicio Cloud",
                "cantidad": 2,
                "precioUnitario": 1250.00,
                "importe": 2500.00,
            }
        ],
    )
    assert valid_res.total == 2900.00

    err_422 = ErrorValidacion422DTO(
        mensaje="Uno o más servicios no existen en el catálogo.",
        errores=[
            {
                "renglon": 2,
                "sku": "SRV-999",
                "mensaje": "El SKU SRV-999 no existe en ListServices.",
            }
        ],
    )
    assert err_422.errores[0].renglon == 2

    creada = FacturaCreadaResponseDTO(
        id=15,
        folio=15,
        serie="A",
        estado="PENDIENTE",
        subtotal=2500.00,
        impuestos=400.00,
        total=2900.00,
    )
    assert creada.estado == "PENDIENTE"

    detalle = FacturaDetalleResponseDTO(
        id=15,
        folio=15,
        serie="A",
        uuid="550e8400-e29b-41d4-a716-446655440000",
        estado="TIMBRADA",
        fechaEmision="2026-11-19T08:30:00Z",
        fechaTimbrado="2026-11-19T08:30:05Z",
        rfcEmisor="UTE980101ABC",
        direccion="Av. Universidad Tecnológica 1",
        comentarios="Servicio mensual",
        formaPago={"clave": "03", "descripcion": "Transferencia electrónica de fondos"},
        metodoPago={"clave": "PUE", "descripcion": "Pago en una sola exhibición"},
        receptor={
            "rfc": "XAXX010101000",
            "razonSocial": "Público en General S.A. de C.V.",
            "codigoPostal": "62760",
            "email": "cliente@empresa.mx",
            "regimenFiscal": "601",
            "usoCfdi": "G03",
        },
        conceptos=[
            {
                "sku": "SRV-001",
                "descripcion": "Servicio Cloud",
                "claveSatProducto": "81112100",
                "claveSatUnidad": "E48",
                "cantidad": 2,
                "precioUnitario": 1250.00,
                "importe": 2500.00,
                "iva": 400.00,
            }
        ],
        subtotal=2500.00,
        impuestos=400.00,
        total=2900.00,
        moneda="MXN",
    )
    assert detalle.moneda == "MXN"

    resumen = ServicioResumenDTO(
        id="SRV-001",
        sku="SRV-001",
        nombre="Servicio Cloud",
        precioUnitario=1250.00,
        descripcion="Descripción",
    )
    assert resumen.sku == "SRV-001"
