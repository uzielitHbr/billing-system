from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


class StrictDTO(BaseModel):
    """Base DTO enforcing strict input/output schemas (blocks Mass Assignment)."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


def format_pydantic_error(exc: ValidationError) -> dict[str, Any]:
    """Format a Pydantic ValidationError into a clean, safe JSON error payload."""
    detalles: list[dict[str, str]] = []
    for err in exc.errors(include_url=False):
        loc_parts = [str(part) for part in err.get("loc", ())]
        campo = ".".join(loc_parts) if loc_parts else "body"
        detalles.append(
            {
                "campo": campo,
                "mensaje": str(err.get("msg", "Valor inválido")),
            }
        )

    return {
        "error": "BAD_REQUEST",
        "mensaje": "Datos de entrada inválidos",
        "detalles": detalles,
    }
