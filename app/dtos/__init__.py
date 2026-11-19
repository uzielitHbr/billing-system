from app.dtos.auth_dto import LoginRequestDTO, LoginResponseDTO
from app.dtos.base import StrictDTO, format_pydantic_error
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

__all__ = [
    "StrictDTO",
    "format_pydantic_error",
    "LoginRequestDTO",
    "LoginResponseDTO",
    "ProductoItemInputDTO",
    "ValidarProductosRequestDTO",
    "ValidacionTotalesResponseDTO",
    "ErrorValidacion422DTO",
    "CrearFacturaRequestDTO",
    "FacturaCreadaResponseDTO",
    "FacturaDetalleResponseDTO",
    "CancelarFacturaRequestDTO",
    "ServicioResumenDTO",
    "ServicioDetalleResponseDTO",
    "agrupar_caracteristicas",
    "build_servicio_detalle",
]
