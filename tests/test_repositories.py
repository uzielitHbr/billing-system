from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import oracledb
import pytest

from app import create_app
from app.repositories.dynamo_repo import DynamoServiceRepository
from app.repositories.oracle_pool import (
    InvoiceNotFoundError,
    InvoiceStateConflictError,
    check_oracle_connection,
    close_oracle_pool,
    oracle_transaction,
    sp_agregar_detalle_factura,
    sp_cancelar_factura,
    sp_consultar_factura_completa,
    sp_crear_factura_borrador,
    sp_listar_catalogos_sat,
    sp_recalcular_totales_factura,
    sp_registrar_bitacora,
    sp_sincronizar_usuario_cognito,
    sp_timbrar_factura,
    sp_upsert_cliente,
)


def _make_var(value):
    var = MagicMock()
    var.getvalue.return_value = value
    return var


def _make_ref_cursor(columns: list[str], rows: list[tuple]):
    cur = MagicMock()
    cur.description = [(col,) for col in columns]
    cur.fetchall.return_value = rows
    return cur


def _make_mock_conn(out_values: list):
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.var.side_effect = [_make_var(val) for val in out_values]

    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def test_sp_1_registrar_bitacora_callproc_order():
    conn, cursor = _make_mock_conn([])
    sp_registrar_bitacora(conn, 15, "CREACION", "Factura creada", "10.0.0.1", "user@utez.edu.mx")
    cursor.callproc.assert_called_once_with(
        "SP_REGISTRAR_BITACORA",
        [15, "CREACION", "Factura creada", "10.0.0.1", "user@utez.edu.mx"],
    )


def test_sp_2_sincronizar_usuario_cognito_callproc_order():
    conn, cursor = _make_mock_conn([7, "ADMIN_ACADEMICO", 1])
    res = sp_sincronizar_usuario_cognito(conn, "sub-123", "user@utez.edu.mx", "Uziel")

    assert cursor.var.call_args_list[0].args == (oracledb.NUMBER,)
    assert cursor.var.call_args_list[1].args == (oracledb.STRING,)
    assert cursor.var.call_args_list[2].args == (oracledb.NUMBER,)

    proc_name, params = cursor.callproc.call_args.args
    assert proc_name == "SP_SINCRONIZAR_USUARIO_COGNITO"
    assert params[:3] == ["sub-123", "user@utez.edu.mx", "Uziel"]
    assert len(params) == 6
    assert res == {"id_usuario": 7, "rol": "ADMIN_ACADEMICO", "activo": 1}


def test_sp_3_listar_catalogos_sat_callproc_and_cursors():
    cur_formas = _make_ref_cursor(["CLAVE", "DESCRIPCION"], [("03", "Transferencia")])
    cur_metodos = _make_ref_cursor(["CLAVE", "DESCRIPCION"], [("PUE", "Una exhibición")])
    cur_regimenes = _make_ref_cursor(
        ["CLAVE", "DESCRIPCION", "APLICA_FISICA", "APLICA_MORAL"],
        [("601", "General de Ley", 0, 1)],
    )
    cur_usos = _make_ref_cursor(["CLAVE", "DESCRIPCION"], [("G03", "Gastos en general")])

    conn, cursor = _make_mock_conn([cur_formas, cur_metodos, cur_regimenes, cur_usos])
    res = sp_listar_catalogos_sat(conn)

    proc_name, params = cursor.callproc.call_args.args
    assert proc_name == "SP_LISTAR_CATALOGOS_SAT"
    assert len(params) == 4
    assert res["formasPago"] == [{"clave": "03", "descripcion": "Transferencia"}]
    assert res["metodosPago"] == [{"clave": "PUE", "descripcion": "Una exhibición"}]
    assert res["regimenesFiscales"] == [
        {
            "clave": "601",
            "descripcion": "General de Ley",
            "aplica_fisica": 0,
            "aplica_moral": 1,
        }
    ]
    assert res["usosCfdi"] == [{"clave": "G03", "descripcion": "Gastos en general"}]


def test_sp_4_upsert_cliente_callproc_order():
    conn, cursor = _make_mock_conn([42])
    id_cliente = sp_upsert_cliente(
        conn, "XAXX010101000", "Público en General", "62760", "601", "G03", "c@e.mx"
    )
    proc_name, params = cursor.callproc.call_args.args
    assert proc_name == "SP_UPSERT_CLIENTE"
    assert params[:6] == [
        "XAXX010101000",
        "Público en General",
        "62760",
        "601",
        "G03",
        "c@e.mx",
    ]
    assert len(params) == 7
    assert id_cliente == 42


def test_sp_5_crear_factura_borrador_callproc_order():
    conn, cursor = _make_mock_conn([15, 1001])
    res = sp_crear_factura_borrador(
        conn, "UTE980101ABC", 42, 7, "03", "PUE", "Av. Universidad 1", "Mensual"
    )
    proc_name, params = cursor.callproc.call_args.args
    assert proc_name == "SP_CREAR_FACTURA_BORRADOR"
    assert params[:7] == [
        "UTE980101ABC",
        42,
        7,
        "03",
        "PUE",
        "Av. Universidad 1",
        "Mensual",
    ]
    assert len(params) == 9
    assert res == {"id_factura": 15, "folio": 1001}


def test_sp_6_agregar_detalle_factura_callproc_order():
    conn, cursor = _make_mock_conn([88])
    id_detalle = sp_agregar_detalle_factura(
        conn, 15, "SRV-001", "Soporte Cloud", 2, Decimal("1250.00")
    )
    proc_name, params = cursor.callproc.call_args.args
    assert proc_name == "SP_AGREGAR_DETALLE_FACTURA"
    assert params[:5] == [15, "SRV-001", "Soporte Cloud", 2, Decimal("1250.00")]
    assert len(params) == 6
    assert id_detalle == 88


def test_sp_7_recalcular_totales_factura_callproc_order():
    conn, cursor = _make_mock_conn([Decimal("2500.00"), Decimal("400.00"), Decimal("2900.00")])
    res = sp_recalcular_totales_factura(conn, 15)
    proc_name, params = cursor.callproc.call_args.args
    assert proc_name == "SP_RECALCULAR_TOTALES_FACTURA"
    assert params[0] == 15
    assert len(params) == 4
    assert res == {"subtotal": 2500.0, "impuestos": 400.0, "total": 2900.0}


def test_sp_8_timbrar_factura_callproc_and_domain_errors():
    now = datetime(2026, 11, 19, 8, 30, 5)
    conn, cursor = _make_mock_conn([15, "A", now])
    res = sp_timbrar_factura(conn, 15, "550e8400-e29b-41d4-a716-446655440000")
    proc_name, params = cursor.callproc.call_args.args
    assert proc_name == "SP_TIMBRAR_FACTURA"
    assert params[:2] == [15, "550e8400-e29b-41d4-a716-446655440000"]
    assert len(params) == 5
    assert res == {"folio": 15, "serie": "A", "fecha_timbrado": now}

    # ORA-20001 -> InvoiceStateConflictError (409)
    conn_20001, cursor_20001 = _make_mock_conn([None, None, None])
    cursor_20001.callproc.side_effect = RuntimeError("ORA-20001: Solo se pueden timbrar")
    with pytest.raises(InvoiceStateConflictError):
        sp_timbrar_factura(conn_20001, 15, "uuid")

    # ORA-20004 -> InvoiceNotFoundError (404)
    conn_20004, cursor_20004 = _make_mock_conn([None, None, None])
    cursor_20004.callproc.side_effect = RuntimeError("ORA-20004: Factura no encontrada")
    with pytest.raises(InvoiceNotFoundError):
        sp_timbrar_factura(conn_20004, 999, "uuid")


def test_sp_9_cancelar_factura_callproc_and_domain_errors():
    conn, cursor = _make_mock_conn([])
    sp_cancelar_factura(conn, 15, "Error de RFC", "user@utez.edu.mx", "10.0.0.1")
    cursor.callproc.assert_called_once_with(
        "SP_CANCELAR_FACTURA",
        [15, "Error de RFC", "user@utez.edu.mx", "10.0.0.1"],
    )

    conn_20002, cursor_20002 = _make_mock_conn([])
    cursor_20002.callproc.side_effect = RuntimeError("ORA-20002: Solo se pueden cancelar")
    with pytest.raises(InvoiceStateConflictError):
        sp_cancelar_factura(conn_20002, 15, "Motivo valido", "user@utez.edu.mx", "10.0.0.1")


def test_sp_10_consultar_factura_completa_callproc_and_cursors():
    cur_cab = _make_ref_cursor(["ID_FACTURA", "ESTADO"], [(15, "TIMBRADA")])
    cur_det = _make_ref_cursor(["ID_DETALLE", "SKU"], [(1, "SRV-001")])
    conn, cursor = _make_mock_conn([cur_cab, cur_det])

    res = sp_consultar_factura_completa(conn, 15)
    proc_name, params = cursor.callproc.call_args.args
    assert proc_name == "SP_CONSULTAR_FACTURA_COMPLETA"
    assert params[0] == 15
    assert len(params) == 3
    assert res == {
        "cabecera": {"id_factura": 15, "estado": "TIMBRADA"},
        "detalles": [{"id_detalle": 1, "sku": "SRV-001"}],
    }

    cur_cab_empty = _make_ref_cursor(["ID_FACTURA"], [])
    cur_det_empty = _make_ref_cursor(["ID_DETALLE"], [])
    conn_empty, _ = _make_mock_conn([cur_cab_empty, cur_det_empty])
    assert sp_consultar_factura_completa(conn_empty, 9999) is None


def test_oracle_transaction_commits_on_success_and_rollbacks_on_failure():
    close_oracle_pool()
    mock_conn = MagicMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_conn

    with patch("app.repositories.oracle_pool.oracledb.create_pool", return_value=mock_pool):
        cfg = {
            "ORACLE_USER": "admin",
            "ORACLE_PASSWORD": "secret",
            "ORACLE_DSN": "host:1521/ORCL",
        }
        with oracle_transaction(config=cfg) as conn:
            assert conn is mock_conn
        mock_conn.commit.assert_called_once()
        mock_conn.rollback.assert_not_called()
        mock_conn.close.assert_called_once()

        mock_conn.reset_mock()
        with pytest.raises(RuntimeError, match="fallo intermedio"):
            with oracle_transaction(config=cfg):
                raise RuntimeError("fallo intermedio")

        mock_conn.commit.assert_not_called()
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    close_oracle_pool()


def test_check_oracle_connection_runs_select_1_from_dual():
    close_oracle_pool()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchone.return_value = (1,)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_conn

    with patch("app.repositories.oracle_pool.oracledb.create_pool", return_value=mock_pool):
        ok = check_oracle_connection(
            {"ORACLE_USER": "u", "ORACLE_PASSWORD": "p", "ORACLE_DSN": "d:1521/ORCL"}
        )
        assert ok is True
        mock_cursor.execute.assert_called_once_with("SELECT 1 FROM DUAL")

    close_oracle_pool()


def test_dynamo_get_service_by_sku_uses_get_item_not_scan_and_preserves_decimal():
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {
            "id_service": "SRV-001",
            "nombre_servicio": "Servicio Cloud",
            "precio_unitario": Decimal("1250.50"),
            "descripcion": "Desc",
        }
    }

    repo = DynamoServiceRepository(table=mock_table)
    item = repo.get_service_by_sku("SRV-001")

    mock_table.get_item.assert_called_once_with(Key={"id_service": "SRV-001"})
    mock_table.scan.assert_not_called()
    assert item is not None
    assert isinstance(item["precio_unitario"], Decimal)
    assert item["precio_unitario"] == Decimal("1250.50")


def test_dynamo_list_all_services_pagination_and_60s_ttl_cache():
    mock_table = MagicMock()
    mock_table.scan.side_effect = [
        {
            "Items": [{"id_service": "SRV-002", "precio_unitario": Decimal("200.00")}],
            "LastEvaluatedKey": {"id_service": "SRV-002"},
        },
        {
            "Items": [{"id_service": "SRV-001", "precio_unitario": Decimal("100.00")}],
        },
        {
            "Items": [{"id_service": "SRV-001", "precio_unitario": Decimal("150.00")}],
        },
    ]

    now = [100.0]
    repo = DynamoServiceRepository(
        table=mock_table,
        cache_ttl_seconds=60.0,
        clock=lambda: now[0],
    )

    first = repo.list_all_services()
    assert [s["id_service"] for s in first] == ["SRV-001", "SRV-002"]
    assert mock_table.scan.call_count == 2

    # Within 60s TTL: served from cache without calling scan()
    now[0] = 159.0
    second = repo.list_all_services()
    assert second == first
    assert mock_table.scan.call_count == 2

    # After 60s TTL expires: refreshes via scan()
    now[0] = 161.0
    third = repo.list_all_services()
    assert mock_table.scan.call_count == 3
    assert third[0]["precio_unitario"] == Decimal("150.00")


def test_health_endpoint_connects_oracle_and_dynamo_checks():
    app = create_app(test_config={"TESTING": False})
    client = app.test_client()

    with (
        patch("app.routes.health_routes.check_oracle_connection", return_value=True) as ora_chk,
        patch("app.routes.health_routes.check_dynamo_connection", return_value=True) as dyn_chk,
    ):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json() == {
            "status": "ok",
            "service": "billing-system-backend",
            "checks": {"flask": "ok", "oracle": "ok", "dynamodb": "ok"},
        }
        ora_chk.assert_called_once()
        dyn_chk.assert_called_once()

    with (
        patch("app.routes.health_routes.check_oracle_connection", return_value=False),
        patch("app.routes.health_routes.check_dynamo_connection", return_value=True),
    ):
        resp_fail = client.get("/health")
        assert resp_fail.status_code == 503
        assert resp_fail.get_json()["status"] == "degraded"
        assert resp_fail.get_json()["checks"]["oracle"] == "error"
