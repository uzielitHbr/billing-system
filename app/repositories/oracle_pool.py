from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import oracledb

logger = logging.getLogger(__name__)

_ORA_CODE_PATTERN = re.compile(r"ORA-(\d+)")


class RepositoryError(Exception):
    """Base exception for repository layer errors."""


class OracleDomainError(RepositoryError):
    """Domain-translated Oracle error safe to propagate upward."""

    def __init__(self, message: str, ora_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.ora_code = ora_code


class InvoiceStateConflictError(OracleDomainError):
    """Raised on ORA-20001 / ORA-20002 state transitions (maps to HTTP 409)."""


class InvoiceNotFoundError(OracleDomainError):
    """Raised on ORA-20004 missing invoice (maps to HTTP 404)."""


def _extract_ora_code(exc: Exception) -> int | None:
    """Extract numeric Oracle error code from an exception instance or message."""
    if exc.args:
        first_arg = exc.args[0]
        code = getattr(first_arg, "code", None)
        if isinstance(code, int):
            return code
    match = _ORA_CODE_PATTERN.search(str(exc))
    if match:
        return int(match.group(1))
    return None


def translate_oracle_error(exc: Exception) -> Exception:
    """Translate known Oracle application/lock errors to domain exceptions."""
    ora_code = _extract_ora_code(exc)
    if ora_code == 20001:
        return InvoiceStateConflictError(
            "Solo se pueden timbrar facturas en estado PENDIENTE.",
            ora_code=20001,
        )
    if ora_code == 20002:
        return InvoiceStateConflictError(
            "Solo se pueden cancelar facturas en estado TIMBRADA.",
            ora_code=20002,
        )
    if ora_code in (20003, 54, 30006):
        return InvoiceStateConflictError(
            "La factura está siendo procesada por otra operación. Intenta nuevamente.",
            ora_code=ora_code,
        )
    if ora_code == 20004:
        return InvoiceNotFoundError(
            "Factura no encontrada.",
            ora_code=20004,
        )
    return exc


DEFAULT_CALL_TIMEOUT_MS = 15000


class OraclePoolManager:
    """Lazy, thread-safe manager for the oracledb thin-mode connection pool."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pool: Any | None = None

    def get_pool(self, config: Mapping[str, Any] | None = None) -> Any:
        if self._pool is not None:
            return self._pool

        with self._lock:
            if self._pool is not None:
                return self._pool

            user = self._read_setting("ORACLE_USER", config)
            password = self._read_setting("ORACLE_PASSWORD", config)
            dsn = self._read_setting("ORACLE_DSN", config)

            if not user or not password or not dsn:
                raise RepositoryError(
                    "Configuración de Oracle incompleta (ORACLE_USER, ORACLE_PASSWORD, ORACLE_DSN)."
                )

            self._pool = oracledb.create_pool(
                user=user,
                password=password,
                dsn=dsn,
                min=1,
                max=10,
                increment=1,
                getmode=oracledb.POOL_GETMODE_TIMEDWAIT,
                wait_timeout=5000,
                timeout=300,
                max_lifetime_session=1800,
                ping_interval=0,
                ping_timeout=3000,
                tcp_connect_timeout=5.0,
                retry_count=2,
                retry_delay=1,
                expire_time=2,
            )
            return self._pool

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                try:
                    self._pool.close(force=True)
                finally:
                    self._pool = None

    @staticmethod
    def _read_setting(key: str, config: Mapping[str, Any] | None) -> str:
        if config and config.get(key):
            return str(config[key]).strip()
        return os.getenv(key, "").strip()


_pool_manager = OraclePoolManager()


def get_oracle_pool(config: Mapping[str, Any] | None = None) -> Any:
    """Return the shared lazy-initialized Oracle connection pool (thin mode)."""
    return _pool_manager.get_pool(config=config)


def close_oracle_pool() -> None:
    """Close and reset the shared Oracle connection pool."""
    _pool_manager.close()


def _acquire_healthy_connection(pool: Any) -> Any:
    """Acquire a verified connection from the pool, replacing dead RDS sockets."""
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            conn = pool.acquire()
        except Exception as exc:
            last_exc = exc
            logger.warning("Oracle pool.acquire() attempt %d failed: %s", attempt + 1, exc)
            continue

        is_healthy_fn = getattr(conn, "is_healthy", None)
        if callable(is_healthy_fn) and is_healthy_fn() is False:
            logger.warning("Discarding unhealthy Oracle connection on attempt %d", attempt + 1)
            drop_fn = getattr(pool, "drop", None)
            if callable(drop_fn):
                drop_fn(conn)
            else:
                conn.close()
            continue

        try:
            conn.call_timeout = DEFAULT_CALL_TIMEOUT_MS
        except Exception:
            pass
        return conn

    if last_exc is not None:
        raise last_exc
    return pool.acquire()


@contextmanager
def oracle_transaction(config: Mapping[str, Any] | None = None) -> Iterator[Any]:
    """Acquire a pooled Oracle connection with automatic commit or rollback."""
    pool = get_oracle_pool(config=config)
    conn = _acquire_healthy_connection(pool)
    try:
        yield conn
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            logger.exception("Failed to rollback Oracle transaction")
        translated = translate_oracle_error(exc)
        if translated is not exc:
            raise translated from exc
        raise
    finally:
        try:
            conn.close()
        except Exception:
            logger.exception("Failed to release Oracle connection back to pool")


def _fetch_ref_cursor(ref_cursor: Any) -> list[dict[str, Any]]:
    """Read all rows from a SYS_REFCURSOR into lowercase-keyed dictionaries."""
    if ref_cursor is None:
        return []
    try:
        description = ref_cursor.description or ()
        columns = [str(col[0]).lower() for col in description]
        rows = ref_cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        close_fn = getattr(ref_cursor, "close", None)
        if callable(close_fn):
            close_fn()


# ---------------------------------------------------------------------------
# Wrappers dedicados de los 10 Stored Procedures (cero SQL concatenado)
# ---------------------------------------------------------------------------

def sp_registrar_bitacora(
    conn: Any,
    id_factura: int | None,
    accion: str,
    descripcion: str,
    ip_origen: str | None,
    usuario: str | None,
) -> None:
    """1. SP_REGISTRAR_BITACORA(p_id_factura, p_accion, p_descripcion, p_ip_origen, p_usuario)."""
    with conn.cursor() as cursor:
        cursor.callproc(
            "SP_REGISTRAR_BITACORA",
            [id_factura, accion, descripcion, ip_origen, usuario],
        )


def sp_sincronizar_usuario_cognito(
    conn: Any,
    cognito_sub: str,
    email: str,
    nombre: str,
) -> dict[str, Any]:
    """2. SP_SINCRONIZAR_USUARIO_COGNITO(IN sub, email, nombre; OUT id_usuario, rol, activo)."""
    with conn.cursor() as cursor:
        p_id_usuario = cursor.var(oracledb.NUMBER)
        p_rol = cursor.var(oracledb.STRING)
        p_activo = cursor.var(oracledb.NUMBER)

        cursor.callproc(
            "SP_SINCRONIZAR_USUARIO_COGNITO",
            [cognito_sub, email, nombre, p_id_usuario, p_rol, p_activo],
        )

        return {
            "id_usuario": int(p_id_usuario.getvalue()),
            "rol": str(p_rol.getvalue()),
            "activo": int(p_activo.getvalue()),
        }


def sp_listar_catalogos_sat(conn: Any) -> dict[str, list[dict[str, Any]]]:
    """3. SP_LISTAR_CATALOGOS_SAT(OUT cur_formas, cur_metodos, cur_regimenes, cur_usos)."""
    with conn.cursor() as cursor:
        p_cur_formas = cursor.var(oracledb.CURSOR)
        p_cur_metodos = cursor.var(oracledb.CURSOR)
        p_cur_regimenes = cursor.var(oracledb.CURSOR)
        p_cur_usos = cursor.var(oracledb.CURSOR)

        cursor.callproc(
            "SP_LISTAR_CATALOGOS_SAT",
            [p_cur_formas, p_cur_metodos, p_cur_regimenes, p_cur_usos],
        )

        return {
            "formasPago": _fetch_ref_cursor(p_cur_formas.getvalue()),
            "metodosPago": _fetch_ref_cursor(p_cur_metodos.getvalue()),
            "regimenesFiscales": _fetch_ref_cursor(p_cur_regimenes.getvalue()),
            "usosCfdi": _fetch_ref_cursor(p_cur_usos.getvalue()),
        }


def sp_upsert_cliente(
    conn: Any,
    rfc: str,
    razon_social: str,
    cp: str,
    regimen: str,
    uso_cfdi: str,
    email: str,
) -> int:
    """4. SP_UPSERT_CLIENTE(IN rfc, razon_social, cp, regimen, uso_cfdi, email; OUT id_cliente)."""
    with conn.cursor() as cursor:
        p_id_cliente = cursor.var(oracledb.NUMBER)
        cursor.callproc(
            "SP_UPSERT_CLIENTE",
            [rfc, razon_social, cp, regimen, uso_cfdi, email, p_id_cliente],
        )
        return int(p_id_cliente.getvalue())


def sp_crear_factura_borrador(
    conn: Any,
    rfc_emisor: str,
    id_cliente: int,
    id_usuario: int,
    forma_pago: str,
    metodo_pago: str,
    direccion: str,
    comentarios: str | None,
) -> dict[str, int]:
    """5. SP_CREAR_FACTURA_BORRADOR(IN ...; OUT id_factura, folio)."""
    with conn.cursor() as cursor:
        p_id_factura = cursor.var(oracledb.NUMBER)
        p_folio = cursor.var(oracledb.NUMBER)
        cursor.callproc(
            "SP_CREAR_FACTURA_BORRADOR",
            [
                rfc_emisor,
                id_cliente,
                id_usuario,
                forma_pago,
                metodo_pago,
                direccion,
                comentarios,
                p_id_factura,
                p_folio,
            ],
        )
        return {
            "id_factura": int(p_id_factura.getvalue()),
            "folio": int(p_folio.getvalue()),
        }


def sp_agregar_detalle_factura(
    conn: Any,
    id_factura: int,
    id_servicio_dynamo: str,
    descripcion: str,
    cantidad: int | float | Decimal,
    precio_unitario: Decimal | float,
) -> int:
    """6. SP_AGREGAR_DETALLE_FACTURA(IN ...; OUT id_detalle)."""
    with conn.cursor() as cursor:
        p_id_detalle = cursor.var(oracledb.NUMBER)
        cursor.callproc(
            "SP_AGREGAR_DETALLE_FACTURA",
            [
                id_factura,
                id_servicio_dynamo,
                descripcion,
                cantidad,
                precio_unitario,
                p_id_detalle,
            ],
        )
        return int(p_id_detalle.getvalue())


def sp_recalcular_totales_factura(conn: Any, id_factura: int) -> dict[str, float]:
    """7. SP_RECALCULAR_TOTALES_FACTURA(IN id_factura; OUT subtotal, impuestos, total)."""
    with conn.cursor() as cursor:
        p_subtotal = cursor.var(oracledb.NUMBER)
        p_impuestos = cursor.var(oracledb.NUMBER)
        p_total = cursor.var(oracledb.NUMBER)
        cursor.callproc(
            "SP_RECALCULAR_TOTALES_FACTURA",
            [id_factura, p_subtotal, p_impuestos, p_total],
        )
        return {
            "subtotal": float(p_subtotal.getvalue()),
            "impuestos": float(p_impuestos.getvalue()),
            "total": float(p_total.getvalue()),
        }


def sp_timbrar_factura(conn: Any, id_factura: int, uuid: str) -> dict[str, Any]:
    """8. SP_TIMBRAR_FACTURA(IN id_factura, uuid; OUT folio, serie, fecha_timbrado)."""
    try:
        with conn.cursor() as cursor:
            p_folio = cursor.var(oracledb.NUMBER)
            p_serie = cursor.var(oracledb.STRING)
            p_fecha_timbrado = cursor.var(oracledb.DB_TYPE_TIMESTAMP)
            cursor.callproc(
                "SP_TIMBRAR_FACTURA",
                [id_factura, uuid, p_folio, p_serie, p_fecha_timbrado],
            )
            return {
                "folio": int(p_folio.getvalue()),
                "serie": str(p_serie.getvalue()),
                "fecha_timbrado": p_fecha_timbrado.getvalue(),
            }
    except Exception as exc:
        translated = translate_oracle_error(exc)
        if translated is not exc:
            raise translated from exc
        raise


def sp_cancelar_factura(
    conn: Any,
    id_factura: int,
    motivo: str,
    usuario: str,
    ip_origen: str | None,
) -> None:
    """9. SP_CANCELAR_FACTURA(IN id_factura, motivo, usuario, ip_origen)."""
    try:
        with conn.cursor() as cursor:
            cursor.callproc(
                "SP_CANCELAR_FACTURA",
                [id_factura, motivo, usuario, ip_origen],
            )
    except Exception as exc:
        translated = translate_oracle_error(exc)
        if translated is not exc:
            raise translated from exc
        raise


def sp_consultar_factura_completa(
    conn: Any,
    id_factura: int,
) -> dict[str, Any] | None:
    """10. SP_CONSULTAR_FACTURA_COMPLETA(IN id_factura; OUT cur_cabecera, cur_detalles)."""
    with conn.cursor() as cursor:
        p_cur_cabecera = cursor.var(oracledb.CURSOR)
        p_cur_detalles = cursor.var(oracledb.CURSOR)
        cursor.callproc(
            "SP_CONSULTAR_FACTURA_COMPLETA",
            [id_factura, p_cur_cabecera, p_cur_detalles],
        )

        cabecera_rows = _fetch_ref_cursor(p_cur_cabecera.getvalue())
        detalles_rows = _fetch_ref_cursor(p_cur_detalles.getvalue())

        if not cabecera_rows:
            return None

        return {
            "cabecera": cabecera_rows[0],
            "detalles": detalles_rows,
        }


def check_oracle_connection(config: Mapping[str, Any] | None = None) -> bool:
    """Execute SELECT 1 FROM DUAL against the Oracle pool for /health."""
    try:
        pool = get_oracle_pool(config=config)
        conn = _acquire_healthy_connection(pool)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM DUAL")
                row = cursor.fetchone()
                return bool(row and row[0] == 1)
        finally:
            conn.close()
    except Exception:
        logger.exception("Oracle health check failed")
        return False
