from __future__ import annotations

from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.dtos.base import StrictDTO

SKU_PATTERN = r"^[A-Z0-9_-]{3,30}$"
RFC_SAT_PATTERN = r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$"
CODIGO_POSTAL_PATTERN = r"^\d{5}$"
CLAVE_SAT_PATTERN = r"^[A-Z0-9]{2,5}$"


class ProductoItemInputDTO(StrictDTO):
    """Line item input for invoice validation/creation. Never accepts precioUnitario."""

    sku: str = Field(..., pattern=SKU_PATTERN)
    cantidad: int = Field(..., ge=1, le=9999)

    @field_validator("cantidad", mode="before")
    @classmethod
    def reject_boolean_or_float_cantidad(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("cantidad debe ser un número entero entre 1 y 9999")
        return value


class ValidarProductosRequestDTO(StrictDTO):
    """Input schema for POST /facturas/validar."""

    productos: list[ProductoItemInputDTO] = Field(..., min_length=1, max_length=100)


class ItemValidadoDTO(StrictDTO):
    """Validated line item priced strictly from DynamoDB ListServices."""

    renglon: int = Field(..., ge=1)
    sku: str
    nombre: str
    cantidad: int = Field(..., ge=1)
    precioUnitario: float = Field(..., ge=0)
    importe: float = Field(..., ge=0)


class ValidacionTotalesResponseDTO(StrictDTO):
    """Output schema 200 for POST /facturas/validar."""

    subtotal: float = Field(..., ge=0)
    impuestos: float = Field(..., ge=0)
    total: float = Field(..., ge=0)
    itemsValidados: list[ItemValidadoDTO]


class ErrorRenglonDTO(StrictDTO):
    """Line-level validation error (1-based index)."""

    renglon: int = Field(..., ge=1)
    sku: str
    mensaje: str


class ErrorValidacion422DTO(StrictDTO):
    """Output schema 422 for POST /facturas/validar."""

    mensaje: str
    errores: list[ErrorRenglonDTO] = Field(..., min_length=1)


class CrearFacturaRequestDTO(StrictDTO):
    """Input schema for POST /facturas."""

    rfcEmisor: str = Field(..., pattern=RFC_SAT_PATTERN)
    rfcReceptor: str = Field(..., pattern=RFC_SAT_PATTERN)
    razonSocial: str = Field(..., min_length=3, max_length=200)
    codigoPostal: str = Field(..., pattern=CODIGO_POSTAL_PATTERN)
    emailReceptor: EmailStr
    regimenFiscal: str = Field(..., min_length=3, max_length=5, pattern=CLAVE_SAT_PATTERN)
    usoCfdi: str = Field(..., min_length=3, max_length=5, pattern=CLAVE_SAT_PATTERN)
    formaPago: str = Field(..., min_length=2, max_length=5, pattern=CLAVE_SAT_PATTERN)
    metodoPago: Literal["PUE", "PPD"]
    direccion: str = Field(..., min_length=5, max_length=255)
    comentarios: str | None = Field(default=None, max_length=400)
    productos: list[ProductoItemInputDTO] = Field(..., min_length=1, max_length=100)


class FacturaCreadaResponseDTO(StrictDTO):
    """Output schema 201 for POST /facturas."""

    id: int = Field(..., ge=1)
    folio: int = Field(..., ge=1)
    serie: str
    estado: Literal["PENDIENTE"] = "PENDIENTE"
    subtotal: float = Field(..., ge=0)
    impuestos: float = Field(..., ge=0)
    total: float = Field(..., ge=0)


class ClaveDescripcionDTO(StrictDTO):
    """Key-description pair from SAT catalogs."""

    clave: str
    descripcion: str


class ReceptorFacturaDTO(StrictDTO):
    """Taxpayer receiver block inside FacturaDetalleResponseDTO."""

    rfc: str
    razonSocial: str
    codigoPostal: str
    email: str
    regimenFiscal: str
    usoCfdi: str


class ConceptoFacturaDTO(StrictDTO):
    """Invoice line item detail inside FacturaDetalleResponseDTO."""

    sku: str
    descripcion: str
    claveSatProducto: str
    claveSatUnidad: str
    cantidad: float = Field(..., gt=0)
    precioUnitario: float = Field(..., ge=0)
    importe: float = Field(..., ge=0)
    iva: float = Field(..., ge=0)


class FacturaDetalleResponseDTO(StrictDTO):
    """Output schema 200 for POST /facturas/{id}/emitir and GET /facturas/{id}."""

    id: int = Field(..., ge=1)
    folio: int = Field(..., ge=1)
    serie: str
    uuid: str | None = None
    fechaEmision: str
    fechaTimbrado: str | None = None
    estado: Literal["PENDIENTE", "TIMBRADA", "CANCELADA"]
    rfcEmisor: str
    direccion: str
    formaPago: ClaveDescripcionDTO
    metodoPago: ClaveDescripcionDTO
    receptor: ReceptorFacturaDTO
    conceptos: list[ConceptoFacturaDTO]
    subtotal: float = Field(..., ge=0)
    impuestos: float = Field(..., ge=0)
    total: float = Field(..., ge=0)
    moneda: str
    comentarios: str | None = None


class CancelarFacturaRequestDTO(StrictDTO):
    """Input schema for POST /facturas/{id}/cancelar."""

    motivo: str = Field(..., min_length=5, max_length=300)
