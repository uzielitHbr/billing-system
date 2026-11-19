from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from io import BytesIO
from typing import Any

import boto3
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.dtos.factura_dto import FacturaDetalleResponseDTO
from app.repositories.oracle_pool import oracle_transaction, sp_registrar_bitacora
from app.services.factura_service import obtener_factura

PRESIGNED_TTL_SECONDS = 300


def _read_setting(key: str, config: Mapping[str, Any] | None, default: str = "") -> str:
    if config and config.get(key):
        return str(config[key]).strip()
    return os.getenv(key, default).strip()


def generate_pdf_bytes(factura: FacturaDetalleResponseDTO) -> bytes:
    """Render a clean corporate invoice PDF with ReportLab."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title=f"Factura {factura.serie}-{factura.folio}")
    styles = getSampleStyleSheet()

    elements: list[Any] = [
        Paragraph(
            f"<b>Comprobante Fiscal Digital - Serie {factura.serie} Folio {factura.folio}</b>",
            styles["Title"],
        ),
        Spacer(1, 10),
        Paragraph(f"<b>Estado:</b> {factura.estado}", styles["Normal"]),
        Paragraph(f"<b>UUID Fiscal:</b> {factura.uuid or 'PENDIENTE DE TIMBRADO'}", styles["Normal"]),
        Paragraph(f"<b>Fecha Emisión:</b> {factura.fechaEmision}", styles["Normal"]),
        Paragraph(
            f"<b>Fecha Timbrado:</b> {factura.fechaTimbrado or 'N/A'}",
            styles["Normal"],
        ),
        Spacer(1, 10),
        Paragraph("<b>Emisor</b>", styles["Heading3"]),
        Paragraph(f"RFC: {factura.rfcEmisor}", styles["Normal"]),
        Paragraph(f"Dirección Fiscal: {factura.direccion}", styles["Normal"]),
        Spacer(1, 8),
        Paragraph("<b>Receptor</b>", styles["Heading3"]),
        Paragraph(f"Razón Social: {factura.receptor.razonSocial}", styles["Normal"]),
        Paragraph(
            f"RFC: {factura.receptor.rfc} | CP: {factura.receptor.codigoPostal} | "
            f"Email: {factura.receptor.email}",
            styles["Normal"],
        ),
        Paragraph(
            f"Régimen Fiscal: {factura.receptor.regimenFiscal} | "
            f"Uso CFDI: {factura.receptor.usoCfdi}",
            styles["Normal"],
        ),
        Paragraph(
            f"Forma de Pago: {factura.formaPago.clave} - {factura.formaPago.descripcion} | "
            f"Método: {factura.metodoPago.clave} - {factura.metodoPago.descripcion}",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]

    table_data: list[list[str]] = [
        ["SKU", "Descripción", "Clave SAT", "Cant.", "P. Unitario", "Importe", "IVA"]
    ]
    for item in factura.conceptos:
        table_data.append(
            [
                item.sku,
                item.descripcion,
                item.claveSatProducto,
                f"{item.cantidad:.2f}",
                f"${item.precioUnitario:,.2f}",
                f"${item.importe:,.2f}",
                f"${item.iva:,.2f}",
            ]
        )

    table = Table(table_data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B365D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    elements.append(table)
    elements.append(Spacer(1, 12))

    elements.extend(
        [
            Paragraph(f"<b>Subtotal:</b> ${factura.subtotal:,.2f} {factura.moneda}", styles["Normal"]),
            Paragraph(f"<b>IVA (16%):</b> ${factura.impuestos:,.2f} {factura.moneda}", styles["Normal"]),
            Paragraph(f"<b>Total:</b> ${factura.total:,.2f} {factura.moneda}", styles["Normal"]),
        ]
    )

    if factura.comentarios:
        elements.append(Spacer(1, 8))
        elements.append(Paragraph(f"<b>Comentarios:</b> {factura.comentarios}", styles["Normal"]))

    doc.build(elements)
    return buffer.getvalue()


def generate_xml_bytes(factura: FacturaDetalleResponseDTO) -> bytes:
    """Build a well-formed simplified CFDI 4.0 XML representation."""
    cfdi_ns = "http://www.sat.gob.mx/cfd/4"
    tfd_ns = "http://www.sat.gob.mx/TimbreFiscalDigital"
    ET.register_namespace("cfdi", cfdi_ns)
    ET.register_namespace("tfd", tfd_ns)

    comprobante = ET.Element(
        f"{{{cfdi_ns}}}Comprobante",
        {
            "Version": "4.0",
            "Serie": factura.serie,
            "Folio": str(factura.folio),
            "Fecha": factura.fechaEmision,
            "FormaPago": factura.formaPago.clave,
            "MetodoPago": factura.metodoPago.clave,
            "SubTotal": f"{factura.subtotal:.2f}",
            "Moneda": factura.moneda,
            "Total": f"{factura.total:.2f}",
            "TipoDeComprobante": "I",
            "Estado": factura.estado,
            "LugarExpedicion": factura.receptor.codigoPostal,
        },
    )

    ET.SubElement(
        comprobante,
        f"{{{cfdi_ns}}}Emisor",
        {"Rfc": factura.rfcEmisor, "DireccionFiscal": factura.direccion},
    )

    ET.SubElement(
        comprobante,
        f"{{{cfdi_ns}}}Receptor",
        {
            "Rfc": factura.receptor.rfc,
            "Nombre": factura.receptor.razonSocial,
            "DomicilioFiscalReceptor": factura.receptor.codigoPostal,
            "RegimenFiscalReceptor": factura.receptor.regimenFiscal,
            "UsoCFDI": factura.receptor.usoCfdi,
        },
    )

    conceptos_el = ET.SubElement(comprobante, f"{{{cfdi_ns}}}Conceptos")
    for item in factura.conceptos:
        concepto_el = ET.SubElement(
            conceptos_el,
            f"{{{cfdi_ns}}}Concepto",
            {
                "NoIdentificacion": item.sku,
                "ClaveProdServ": item.claveSatProducto,
                "ClaveUnidad": item.claveSatUnidad,
                "Cantidad": f"{item.cantidad:.2f}",
                "Descripcion": item.descripcion,
                "ValorUnitario": f"{item.precioUnitario:.2f}",
                "Importe": f"{item.importe:.2f}",
            },
        )
        impuestos_c = ET.SubElement(concepto_el, f"{{{cfdi_ns}}}Impuestos")
        traslados_c = ET.SubElement(impuestos_c, f"{{{cfdi_ns}}}Traslados")
        ET.SubElement(
            traslados_c,
            f"{{{cfdi_ns}}}Traslado",
            {
                "Base": f"{item.importe:.2f}",
                "Impuesto": "002",
                "TipoFactor": "Tasa",
                "TasaOCuota": "0.160000",
                "Importe": f"{item.iva:.2f}",
            },
        )

    ET.SubElement(
        comprobante,
        f"{{{cfdi_ns}}}Impuestos",
        {"TotalImpuestosTrasladados": f"{factura.impuestos:.2f}"},
    )

    if factura.uuid:
        complemento = ET.SubElement(comprobante, f"{{{cfdi_ns}}}Complemento")
        ET.SubElement(
            complemento,
            f"{{{tfd_ns}}}TimbreFiscalDigital",
            {
                "Version": "1.1",
                "UUID": factura.uuid,
                "FechaTimbrado": factura.fechaTimbrado or factura.fechaEmision,
            },
        )

    return ET.tostring(comprobante, encoding="utf-8", xml_declaration=True)


def exportar_factura(
    id_factura: int,
    formato: str,
    current_user: Mapping[str, Any],
    client_ip: str,
    config: Mapping[str, Any] | None = None,
    s3_client: Any | None = None,
) -> dict[str, Any]:
    """Generate PDF or XML, upload to private S3 bucket, audit in Oracle, return pre-signed URL."""
    normalized_format = formato.strip().lower()
    if normalized_format not in ("pdf", "xml"):
        raise ValueError("Formato inválido. Valores permitidos: pdf, xml.")

    factura = obtener_factura(id_factura=id_factura, config=config)

    if normalized_format == "pdf":
        file_bytes = generate_pdf_bytes(factura)
        content_type = "application/pdf"
        accion_bitacora = "EXPORTACION_PDF"
    else:
        file_bytes = generate_xml_bytes(factura)
        content_type = "application/xml"
        accion_bitacora = "EXPORTACION_XML"

    bucket = _read_setting("S3_BUCKET_COMPROBANTES", config)
    region = _read_setting("AWS_REGION", config, "us-east-1")
    if not bucket:
        raise RuntimeError("S3_BUCKET_COMPROBANTES no configurado")

    s3_key = f"facturas/{id_factura}/factura_{factura.serie}_{factura.folio}.{normalized_format}"
    client = s3_client or boto3.client("s3", region_name=region)

    client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=file_bytes,
        ContentType=content_type,
    )

    presigned_url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": s3_key},
        ExpiresIn=PRESIGNED_TTL_SECONDS,
    )

    with oracle_transaction(config=config) as conn:
        sp_registrar_bitacora(
            conn,
            id_factura=id_factura,
            accion=accion_bitacora,
            descripcion=f"Exportación {normalized_format.upper()} generada: {s3_key}",
            ip_origen=client_ip,
            usuario=str(current_user["email"]),
        )

    return {
        "formato": normalized_format,
        "url": presigned_url,
        "expiraEnSegundos": PRESIGNED_TTL_SECONDS,
    }
