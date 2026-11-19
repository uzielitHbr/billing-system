from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import Field

from app.dtos.base import StrictDTO

CARACTERISTICA_GRUPOS: tuple[tuple[str, str, int, int], ...] = (
    ("fiscal_legal", "Fiscal y legal", 1, 12),
    ("identificacion", "Identificación", 13, 22),
    ("comercial", "Comercial", 23, 32),
    ("contractual", "Contractual", 33, 41),
    ("operativa", "Operativa", 42, 50),
)


class ServicioResumenDTO(StrictDTO):
    """Output schema for items in GET /servicios."""

    id: str
    sku: str
    nombre: str
    precioUnitario: float = Field(..., ge=0)
    descripcion: str


class ServicioAtributoDTO(StrictDTO):
    """Single attribute entry inside a service characteristic section."""

    clave: str
    etiqueta: str
    valor: str


class ServicioSeccionDTO(StrictDTO):
    """Grouped section of service characteristics."""

    id: str
    titulo: str
    atributos: list[ServicioAtributoDTO]


class ServicioDetalleResponseDTO(ServicioResumenDTO):
    """Output schema for GET /servicios/{id} with 50 grouped characteristics."""

    secciones: list[ServicioSeccionDTO]


def agrupar_caracteristicas(
    caracteristicas: Mapping[str, Any] | None,
) -> list[ServicioSeccionDTO]:
    """Group DynamoDB caracteristica_01..caracteristica_50 into the 5 exact sections."""
    source = caracteristicas or {}
    secciones: list[ServicioSeccionDTO] = []

    for grupo_id, titulo, inicio, fin in CARACTERISTICA_GRUPOS:
        atributos: list[ServicioAtributoDTO] = []
        for idx in range(inicio, fin + 1):
            clave = f"caracteristica_{idx:02d}"
            raw_valor = source.get(clave)
            valor = "" if raw_valor is None else str(raw_valor)
            atributos.append(
                ServicioAtributoDTO(
                    clave=clave,
                    etiqueta=f"Característica {idx:02d}",
                    valor=valor,
                )
            )
        secciones.append(
            ServicioSeccionDTO(
                id=grupo_id,
                titulo=titulo,
                atributos=atributos,
            )
        )

    return secciones


def build_servicio_detalle(item: Mapping[str, Any]) -> ServicioDetalleResponseDTO:
    """Build ServicioDetalleResponseDTO from a raw DynamoDB ListServices item."""
    service_id = str(item["id_service"])
    return ServicioDetalleResponseDTO(
        id=service_id,
        sku=service_id,
        nombre=str(item.get("nombre_servicio", "")),
        precioUnitario=float(item.get("precio_unitario", 0)),
        descripcion=str(item.get("descripcion", "")),
        secciones=agrupar_caracteristicas(item.get("caracteristicas")),
    )
