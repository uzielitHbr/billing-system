from __future__ import annotations

import sys
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import create_app
from app.repositories.oracle_pool import (
    InvoiceNotFoundError,
    InvoiceStateConflictError,
    close_oracle_pool,
)
from app.security.jwt_validator import clear_jwk_client_cache

REGION = "us-east-1"
POOL_ID = "us-east-1_fWBs2LMa3"
CLIENT_ID = "1dhc6l396sgg79cl4qbn8shqn2"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL_ID}"
BUCKET = "billing-comprobantes-ute"


@pytest.fixture(scope="module")
def rsa_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _auth_header(private_key) -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "sub-111",
            "email": "20243ds112@utez.edu.mx",
            "name": "Uziel Abraham",
            "token_use": "id",
            "aud": CLIENT_ID,
            "iss": ISSUER,
            "iat": now,
            "exp": now + 3600,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "kid-1"},
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Forwarded-For": "187.10.20.30",
    }


@contextmanager
def _fake_tx():
    yield MagicMock()


@pytest.fixture()
def client(rsa_keys):
    clear_jwk_client_cache()
    _, public_key = rsa_keys
    mock_jwk_client = MagicMock()
    mock_jwk_client.get_signing_key_from_jwt.return_value = SimpleNamespace(key=public_key)

    app = create_app(
        test_config={
            "TESTING": True,
            "AWS_REGION": REGION,
            "COGNITO_USER_POOL_ID": POOL_ID,
            "COGNITO_CLIENT_ID": CLIENT_ID,
            "S3_BUCKET_COMPROBANTES": BUCKET,
        }
    )

    with (
        patch("app.security.jwt_validator.get_jwk_client", return_value=mock_jwk_client),
        patch("app.security.jwt_validator.oracle_transaction", side_effect=lambda **_: _fake_tx()),
        patch(
            "app.security.jwt_validator.sp_sincronizar_usuario_cognito",
            return_value={"id_usuario": 1, "rol": "ADMIN_ACADEMICO", "activo": 1},
        ),
    ):
        yield app.test_client()

    clear_jwk_client_cache()


def _sample_crear_payload() -> dict:
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


def _sample_raw_factura(estado: str = "TIMBRADA") -> dict:
    uuid_val = "550e8400-e29b-41d4-a716-446655440000" if estado != "PENDIENTE" else None
    timbrado_val = datetime(2026, 11, 19, 8, 30, 5) if estado != "PENDIENTE" else None
    return {
        "cabecera": {
            "id_factura": 15,
            "folio_fiscal_uuid": uuid_val,
            "serie": "A",
            "folio": 15,
            "rfc_emisor": "UTE980101ABC",
            "direccion_fiscal": "Av. Universidad Tecnológica 1",
            "comentarios": "Servicio mensual",
            "subtotal": Decimal("2500.00"),
            "total_impuestos": Decimal("400.00"),
            "total": Decimal("2900.00"),
            "moneda": "MXN",
            "estado": estado,
            "fecha_emision": datetime(2026, 11, 19, 8, 30, 0),
            "fecha_timbrado": timbrado_val,
            "rfc_receptor": "XAXX010101000",
            "razon_social": "Público en General S.A. de C.V.",
            "codigo_postal": "62760",
            "email_receptor": "cliente@empresa.mx",
            "id_regimen_fiscal": "601",
            "regimen_descripcion": "General de Ley Personas Morales",
            "id_uso_cfdi": "G03",
            "uso_cfdi_descripcion": "Gastos en general",
            "id_forma_pago": "03",
            "forma_pago_descripcion": "Transferencia electrónica de fondos",
            "id_metodo_pago": "PUE",
            "metodo_pago_descripcion": "Pago en una sola exhibición",
            "usuario_creador": "20243ds112@utez.edu.mx",
        },
        "detalles": [
            {
                "id_detalle": 1,
                "sku": "SRV-001",
                "descripcion_item": "Alojamiento Cloud",
                "clave_sat_producto": "81112100",
                "clave_sat_unidad": "E48",
                "cantidad": Decimal("2"),
                "precio_unitario": Decimal("1250.00"),
                "importe": Decimal("2500.00"),
                "descuento": Decimal("0.00"),
                "tasa_iva": Decimal("0.1600"),
                "importe_iva": Decimal("400.00"),
            }
        ],
    }


def test_validar_productos_200_decimal_exact_and_422_base_1(client, rsa_keys):
    private_key, _ = rsa_keys
    headers = _auth_header(private_key)

    catalog = {
        "SRV-001": {
            "id_service": "SRV-001",
            "nombre_servicio": "Micro Servicio",
            "precio_unitario": Decimal("19.99"),
        }
    }

    with patch(
        "app.services.factura_service.get_service_by_sku",
        side_effect=lambda sku, config=None: catalog.get(sku),
    ):
        # 19.99 * 3 = 59.97; IVA ROUND_HALF_UP(59.97 * 0.16 = 9.5952) = 9.60; total = 69.57
        resp_ok = client.post(
            "/facturas/validar",
            json={"productos": [{"sku": "SRV-001", "cantidad": 3}]},
            headers=headers,
        )
        assert resp_ok.status_code == 200
        body_ok = resp_ok.get_json()
        assert body_ok["subtotal"] == 59.97
        assert body_ok["impuestos"] == 9.60
        assert body_ok["total"] == 69.57
        assert body_ok["itemsValidados"][0]["renglon"] == 1

        # Second item invalid -> HTTP 422 with renglon == 2 (base-1)
        resp_422 = client.post(
            "/facturas/validar",
            json={
                "productos": [
                    {"sku": "SRV-001", "cantidad": 1},
                    {"sku": "SRV-999", "cantidad": 1},
                ]
            },
            headers=headers,
        )
        assert resp_422.status_code == 422
        body_422 = resp_422.get_json()
        assert body_422["errores"] == [
            {
                "renglon": 2,
                "sku": "SRV-999",
                "mensaje": "El SKU SRV-999 no existe en ListServices.",
            }
        ]


def test_crear_factura_rejects_tampered_price_400_and_rolls_back_on_sp_failure(client, rsa_keys):
    private_key, _ = rsa_keys
    headers = _auth_header(private_key)

    # Mass assignment / tampered precioUnitario -> 400
    bad_payload = _sample_crear_payload()
    bad_payload["productos"] = [{"sku": "SRV-001", "cantidad": 2, "precioUnitario": 0.01}]
    resp_400 = client.post("/facturas", json=bad_payload, headers=headers)
    assert resp_400.status_code == 400

    # Successful creation -> 201
    service = {
        "id_service": "SRV-001",
        "nombre_servicio": "Alojamiento Cloud",
        "precio_unitario": Decimal("1250.00"),
    }
    with (
        patch("app.services.factura_service.get_service_by_sku", return_value=service),
        patch("app.services.factura_service.oracle_transaction", side_effect=lambda **_: _fake_tx()),
        patch("app.services.factura_service.sp_upsert_cliente", return_value=42),
        patch(
            "app.services.factura_service.sp_crear_factura_borrador",
            return_value={"id_factura": 15, "folio": 15},
        ),
        patch("app.services.factura_service.sp_agregar_detalle_factura", return_value=101),
        patch(
            "app.services.factura_service.sp_recalcular_totales_factura",
            return_value={"subtotal": 2500.0, "impuestos": 400.0, "total": 2900.0},
        ),
        patch("app.services.factura_service.sp_registrar_bitacora") as bitacora_mock,
    ):
        resp_201 = client.post("/facturas", json=_sample_crear_payload(), headers=headers)
        assert resp_201.status_code == 201
        assert resp_201.get_json() == {
            "id": 15,
            "folio": 15,
            "serie": "A",
            "estado": "PENDIENTE",
            "subtotal": 2500.0,
            "impuestos": 400.0,
            "total": 2900.0,
        }
        assert bitacora_mock.call_args.kwargs["accion"] == "CREACION_BORRADOR"

    # Atomic rollback if SP fails mid-transaction
    close_oracle_pool()
    mock_conn = MagicMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_conn

    with (
        patch("app.services.factura_service.get_service_by_sku", return_value=service),
        patch("app.repositories.oracle_pool.oracledb.create_pool", return_value=mock_pool),
        patch.dict(
            client.application.config,
            {"ORACLE_USER": "u", "ORACLE_PASSWORD": "p", "ORACLE_DSN": "d:1521/ORCL"},
        ),
        patch("app.services.factura_service.sp_upsert_cliente", return_value=42),
        patch(
            "app.services.factura_service.sp_crear_factura_borrador",
            return_value={"id_factura": 15, "folio": 15},
        ),
        patch(
            "app.services.factura_service.sp_agregar_detalle_factura",
            side_effect=RuntimeError("ORA-12899: value too large"),
        ),
    ):
        resp_500 = client.post("/facturas", json=_sample_crear_payload(), headers=headers)
        assert resp_500.status_code == 500
        assert "ORA-" not in resp_500.get_data(as_text=True)
        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    close_oracle_pool()


def test_obtener_emitir_and_cancelar_factura_flows(client, rsa_keys):
    private_key, _ = rsa_keys
    headers = _auth_header(private_key)

    # GET /facturas/15 -> 200
    with (
        patch("app.services.factura_service.oracle_transaction", side_effect=lambda **_: _fake_tx()),
        patch(
            "app.services.factura_service.sp_consultar_factura_completa",
            return_value=_sample_raw_factura("PENDIENTE"),
        ),
    ):
        resp_get = client.get("/facturas/15", headers=headers)
        assert resp_get.status_code == 200
        assert resp_get.get_json()["estado"] == "PENDIENTE"

    # POST /facturas/15/emitir -> 200
    with (
        patch("app.services.factura_service.oracle_transaction", side_effect=lambda **_: _fake_tx()),
        patch(
            "app.services.factura_service.sp_timbrar_factura",
            return_value={"folio": 15, "serie": "A", "fecha_timbrado": datetime(2026, 11, 19, 8, 30, 5)},
        ),
        patch("app.services.factura_service.sp_registrar_bitacora") as bit_emit,
        patch(
            "app.services.factura_service.sp_consultar_factura_completa",
            return_value=_sample_raw_factura("TIMBRADA"),
        ),
    ):
        resp_emit = client.post("/facturas/15/emitir", headers=headers)
        assert resp_emit.status_code == 200
        data_emit = resp_emit.get_json()
        assert data_emit["estado"] == "TIMBRADA"
        assert data_emit["uuid"] == "550e8400-e29b-41d4-a716-446655440000"
        assert bit_emit.call_args.kwargs["accion"] == "TIMBRADO"

    # POST /facturas/15/emitir when already TIMBRADA -> 409
    with (
        patch("app.services.factura_service.oracle_transaction", side_effect=lambda **_: _fake_tx()),
        patch(
            "app.services.factura_service.sp_timbrar_factura",
            side_effect=InvoiceStateConflictError("Solo se pueden timbrar facturas PENDIENTE", 20001),
        ),
    ):
        resp_emit_409 = client.post("/facturas/15/emitir", headers=headers)
        assert resp_emit_409.status_code == 409

    # POST /facturas/999/emitir -> 404
    with (
        patch("app.services.factura_service.oracle_transaction", side_effect=lambda **_: _fake_tx()),
        patch(
            "app.services.factura_service.sp_timbrar_factura",
            side_effect=InvoiceNotFoundError("Factura no encontrada", 20004),
        ),
    ):
        resp_emit_404 = client.post("/facturas/999/emitir", headers=headers)
        assert resp_emit_404.status_code == 404

    # POST /facturas/15/cancelar -> 200
    with (
        patch("app.services.factura_service.oracle_transaction", side_effect=lambda **_: _fake_tx()),
        patch("app.services.factura_service.sp_cancelar_factura") as sp_cancel,
    ):
        resp_cancel = client.post(
            "/facturas/15/cancelar",
            json={"motivo": "Error en RFC del receptor"},
            headers=headers,
        )
        assert resp_cancel.status_code == 200
        assert resp_cancel.get_json() == {"id": 15, "estado": "CANCELADA"}
        sp_cancel.assert_called_once()

    # POST /facturas/15/cancelar when not TIMBRADA -> 409
    with (
        patch("app.services.factura_service.oracle_transaction", side_effect=lambda **_: _fake_tx()),
        patch(
            "app.services.factura_service.sp_cancelar_factura",
            side_effect=InvoiceStateConflictError("Solo se pueden cancelar facturas TIMBRADA", 20002),
        ),
    ):
        resp_cancel_409 = client.post(
            "/facturas/15/cancelar",
            json={"motivo": "Error en RFC del receptor"},
            headers=headers,
        )
        assert resp_cancel_409.status_code == 409


def test_exportar_pdf_and_xml_upload_to_s3_and_audit(client, rsa_keys):
    private_key, _ = rsa_keys
    headers = _auth_header(private_key)

    mock_s3 = MagicMock()
    mock_s3.generate_presigned_url.return_value = (
        f"https://{BUCKET}.s3.amazonaws.com/facturas/15/factura_A_15.pdf?X-Amz-Expires=300"
    )

    with (
        patch("app.services.factura_service.oracle_transaction", side_effect=lambda **_: _fake_tx()),
        patch(
            "app.services.factura_service.sp_consultar_factura_completa",
            return_value=_sample_raw_factura("TIMBRADA"),
        ),
        patch("app.services.export_service.oracle_transaction", side_effect=lambda **_: _fake_tx()),
        patch("app.services.export_service.sp_registrar_bitacora") as bit_export,
        patch("app.services.export_service.boto3.client", return_value=mock_s3),
    ):
        # PDF export
        resp_pdf = client.get("/facturas/15/exportar?formato=pdf", headers=headers)
        assert resp_pdf.status_code == 200
        pdf_json = resp_pdf.get_json()
        assert pdf_json["formato"] == "pdf"
        assert pdf_json["expiraEnSegundos"] == 300

        put_pdf_kwargs = mock_s3.put_object.call_args.kwargs
        assert put_pdf_kwargs["Bucket"] == BUCKET
        assert put_pdf_kwargs["Key"] == "facturas/15/factura_A_15.pdf"
        assert put_pdf_kwargs["Body"].startswith(b"%PDF")
        assert bit_export.call_args.kwargs["accion"] == "EXPORTACION_PDF"

        # XML export
        mock_s3.reset_mock()
        bit_export.reset_mock()
        resp_xml = client.get("/facturas/15/exportar?formato=xml", headers=headers)
        assert resp_xml.status_code == 200
        xml_json = resp_xml.get_json()
        assert xml_json["formato"] == "xml"
        assert xml_json["expiraEnSegundos"] == 300

        put_xml_kwargs = mock_s3.put_object.call_args.kwargs
        assert put_xml_kwargs["Key"] == "facturas/15/factura_A_15.xml"
        parsed_root = ET.fromstring(put_xml_kwargs["Body"])
        assert parsed_root.tag.endswith("Comprobante")
        assert bit_export.call_args.kwargs["accion"] == "EXPORTACION_XML"

        # Invalid format -> 400
        resp_bad = client.get("/facturas/15/exportar?formato=docx", headers=headers)
        assert resp_bad.status_code == 400


def test_seed_realistic_services_catalog_integrity_and_batch_write():
    from scripts.seed_realistic_services import build_realistic_services, seed_dynamodb

    items = build_realistic_services()
    assert len(items) == 100
    assert [item["id_service"] for item in items] == [f"SRV-{i:03d}" for i in range(1, 101)]
    assert len({item["nombre_servicio"] for item in items}) == 100
    assert all(isinstance(item["precio_unitario"], Decimal) for item in items)
    assert all(len(item["caracteristicas"]) == 50 for item in items)

    mock_batch = MagicMock()
    mock_table = MagicMock()
    mock_table.batch_writer.return_value.__enter__.return_value = mock_batch
    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table

    with patch("scripts.seed_realistic_services.boto3.resource", return_value=mock_resource):
        seed_dynamodb(items=items, table_name="ListServices", region_name="us-east-1")

    mock_table.batch_writer.assert_called_once_with(overwrite_by_pkeys=["id_service"])
    assert mock_batch.put_item.call_count == 100
