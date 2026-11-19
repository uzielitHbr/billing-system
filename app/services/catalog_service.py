from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from app.dtos.servicio_dto import (
    ServicioDetalleResponseDTO,
    ServicioResumenDTO,
    build_servicio_detalle,
)
from app.repositories.dynamo_repo import get_service_by_sku, list_all_services
from app.repositories.oracle_pool import oracle_transaction, sp_listar_catalogos_sat


class ServiceNotFoundError(Exception):
    """Raised when a requested service SKU does not exist in DynamoDB ListServices."""

    def __init__(self, sku: str) -> None:
        super().__init__(f"Servicio '{sku}' no encontrado")
        self.sku = sku


def get_sat_catalogs(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Fetch active SAT catalogs from Oracle via SP_LISTAR_CATALOGOS_SAT."""
    with oracle_transaction(config=config) as conn:
        return sp_listar_catalogos_sat(conn)


def search_services(
    query: str = "",
    page: int = 1,
    limit: int = 20,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Filter cached DynamoDB ListServices catalog and return paginated summary DTOs."""
    all_items = list_all_services(config=config)

    normalized_query = query.strip().lower()
    if normalized_query:
        filtered = [
            item
            for item in all_items
            if normalized_query in str(item.get("id_service", "")).lower()
            or normalized_query in str(item.get("nombre_servicio", "")).lower()
            or normalized_query in str(item.get("descripcion", "")).lower()
        ]
    else:
        filtered = all_items

    total = len(filtered)
    total_pages = math.ceil(total / limit) if total > 0 else 0
    offset = (page - 1) * limit
    page_items = filtered[offset : offset + limit]

    items_dto = [
        ServicioResumenDTO(
            id=str(item["id_service"]),
            sku=str(item["id_service"]),
            nombre=str(item.get("nombre_servicio", "")),
            precioUnitario=float(item.get("precio_unitario", 0)),
            descripcion=str(item.get("descripcion", "")),
        ).model_dump()
        for item in page_items
    ]

    return {
        "items": items_dto,
        "total": total,
        "page": page,
        "limit": limit,
        "totalPages": total_pages,
    }


def get_service_detail(
    service_id: str,
    config: Mapping[str, Any] | None = None,
) -> ServicioDetalleResponseDTO:
    """Fetch a single service in O(1) from DynamoDB and group its 50 characteristics."""
    item = get_service_by_sku(service_id, config=config)
    if item is None:
        raise ServiceNotFoundError(service_id)
    return build_servicio_detalle(item)
