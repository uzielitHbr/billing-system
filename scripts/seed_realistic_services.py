#!/usr/bin/env python3
"""Seed 100 realistic university and technology services into DynamoDB ListServices."""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import boto3
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_boto3_config  # noqa: E402
from app.dtos.servicio_dto import build_servicio_detalle  # noqa: E402

# (categoria, clave_sat, unidad_sat, modalidad, area_utez, sla, horario, servicios: [(nombre, precio, descripcion)])
_CATALOG_SPEC: list[tuple[str, str, str, str, str, str, str, list[tuple[str, str, str]]]] = [
    (
        "Licencias de Software",
        "43231500",
        "E48",
        "Suscripción Digital Institucional",
        "Dirección de Tecnologías de la Información (DTI)",
        "99.5% disponibilidad de portal de licenciamiento",
        "Lunes a Viernes 08:00 - 18:00",
        [
            ("Licencia Anual Suite CAD/CAM Ingeniería", "4850.00", "Suscripción educativa anual de diseño asistido por computadora y manufactura 3D para talleres de ingeniería."),
            ("Licencia Anual Simulador de Circuitos y PCB", "2900.00", "Entorno profesional de simulación electrónica analógica, digital y diseño de tarjetas impresas multicapa."),
            ("Suscripción IDE Profesional Multiplataforma (Paquete 25 Puestos)", "6400.00", "Licenciamiento académico anual para entornos integrados de desarrollo en Java, Python, C++ y TypeScript."),
            ("Licencia Plataforma Estadística y Minería de Datos", "3750.00", "Software especializado para análisis multivariado, series de tiempo y modelado predictivo académico."),
            ("Licencia Anual Motor Base de Datos Empresarial", "8200.00", "Edición académica avanzada con herramientas de modelado relacional, tuning y replicación en laboratorio."),
            ("Suite Edición Audiovisual y Diseño Gráfico Digital", "4100.00", "Paquete creativo completo para edición de video 4K, ilustración vectorial y maquetación editorial."),
            ("Licencia Software Gestión de Proyectos Ágiles (50 Usuarios)", "3250.00", "Plataforma colaborativa con tableros Kanban, seguimiento de sprints y control de entregas académicas."),
            ("Licencia Antivirus y Protección Endpoint Campus (100 Nodos)", "7500.00", "Consola centralizada de protección antimalware, control de dispositivos USB y respuesta ante amenazas."),
            ("Suscripción Plataforma Simulación de Redes Cisco/Virtual", "3600.00", "Simulador avanzado de enrutamiento, conmutación VLAN, BGP y seguridad perimetral para prácticas."),
            ("Licencia Software Contabilidad Electrónica y Nómina CFDI", "2450.00", "Sistema fiscal actualizado para prácticas contables, timbrado simulado y conciliación bancaria."),
            ("Licencia Herramienta BI y Visualización Analítica", "3900.00", "Conectores nativos para tableros ejecutivos, modelado DAX y publicación segura de reportes."),
            ("Suscripción Sistema Gestión Bibliotecaria y Repositorio", "5100.00", "Módulo de catalogación MARC21, préstamo digital y preservación de tesis de grado."),
            ("Licencia Suite Virtualización Desktop Hypervisor Pro", "2800.00", "Licenciamiento para ejecución simultánea de máquinas virtuales Linux, Windows Server y contenedores."),
            ("Licencia Software Análisis Estructural y Elemento Finito", "5600.00", "Módulo de cálculo mecánico, análisis térmico y esfuerzo estructural para proyectos de mecatrónica."),
            ("Suscripción Plataforma Antiplagio Académico Anual", "6900.00", "Verificación automática de originalidad documental con repositorio institucional integrado."),
        ],
    ),
    (
        "Infraestructura Cloud",
        "81112100",
        "E48",
        "Aprovisionamiento Cloud Administrado",
        "Coordinación de Infraestructura y Nube UTEZ",
        "99.9% uptime mensual garantizado",
        "Operación 24/7 con monitoreo automatizado",
        [
            ("Instancia Cómputo Virtual 4 vCPU / 16 GB RAM (Mensual)", "1850.00", "Servidor virtual Linux endurecido con IP privada, snapshots diarios y monitoreo CloudWatch."),
            ("Instancia Cómputo Alto Rendimiento GPU Tensor (Mensual)", "7900.00", "Nodo virtual acelerado por GPU para entrenamiento de redes neuronales y visión por computadora."),
            ("Clúster Kubernetes Administrado Desarrollo (Mensual)", "5400.00", "Plano de control administrado con 3 nodos worker, balanceador interno y registro de contenedores."),
            ("Base de Datos Relacional Administrada Oracle/Postgres (Mensual)", "4650.00", "Instancia RDS con respaldos automáticos diarios, cifrado en reposo KMS y ventana de mantenimiento."),
            ("Almacenamiento Objetos S3 Privado 2 TB con Versionado", "950.00", "Bucket privado con políticas IAM de mínimo privilegio, cifrado SSE-S3 y ciclo de vida automático."),
            ("Balanceador de Carga Aplicación + WAF Administrado", "1600.00", "Proxy inverso de alta disponibilidad con reglas OWASP Core Rule Set y limitación de tasa por IP."),
            ("Red Privada Virtual Site-to-Site IPsec Campus-AWS", "2100.00", "Túnel cifrado redundante entre red universitaria y VPC productiva con enrutamiento privado."),
            ("Entorno Serverless API Gateway + Lambda (Paquete 5M Req)", "1350.00", "Arquitectura orientada a eventos sin servidor con logs centralizados y escalado automático."),
            ("Registro Privado Contenedores Docker + Escaneo CVE", "1100.00", "Repositorio privado de imágenes OCI con análisis automático de vulnerabilidades en cada push."),
            ("Servicio CDN Distribución Global y Certificados TLS", "1450.00", "Entrega de activos estáticos con compresión Brotli, invalidación programática y TLS 1.3."),
            ("Respaldo Inmutable Disaster Recovery Cross-Region (1 TB)", "2300.00", "Replicación asíncrona encriptada hacia región secundaria con pruebas trimestrales de restauración."),
            ("Plataforma Observabilidad Logs, Métricas y Trazas APM", "2750.00", "Recolección unificada de métricas de sistema, journald y alertas tempranas en tiempo real."),
            ("Base de Datos NoSQL Baja Latencia 500 RCU/WCU", "1950.00", "Tabla administrada llave-valor con Point-in-Time Recovery y autoescalado de capacidad."),
            ("Servidor Correo Transaccional SMTP Verificado SPF/DKIM", "890.00", "Servicio de envío de notificaciones institucionales con reputación monitoreada y estadísticas de rebote."),
            ("Sandbox Cloud Aislado para Equipos de Titulación (10 Cuentas)", "3400.00", "Entornos efímeros con presupuestos acotados, guardrails IAM y apagado automático nocturno."),
        ],
    ),
    (
        "Laboratorios Especializados",
        "86121700",
        "ACT",
        "Presencial / Acceso Remoto VPN",
        "División Académica de Tecnologías de la Información",
        "Disponibilidad programada según calendario de reserva",
        "Lunes a Sábado 07:00 - 21:00",
        [
            ("Renta Hora Laboratorio Cómputo Mac/Linux (30 Estaciones)", "1200.00", "Uso exclusivo de sala equipada con 30 estaciones de trabajo, proyector 4K y red gigabit."),
            ("Acceso Laboratorio Ciberseguridad y Pentesting Aislado", "2650.00", "Red segmentada sandbox con escenarios Kali Linux, SIEM y máquinas vulnerables controladas."),
            ("Uso Laboratorio IoT, Sensores Industriales y Microcontroladores", "1900.00", "Estaciones equipadas con osciloscopios digitales, gateways LoRaWAN, ESP32 y analizadores lógicos."),
            ("Práctica en Laboratorio Manufactura CNC y Corte Láser", "3100.00", "Tiempo de máquina supervisado en fresadora CNC de 3 ejes y cortadora láser de precisión."),
            ("Sesión Laboratorio Impresión 3D Resina y Filamento Técnico", "1450.00", "Fabricación aditiva de prototipos funcionales en PLA+, PETG, ABS o resina fotopolimérica."),
            ("Uso Laboratorio Robótica Colaborativa y Visión Artificial", "3500.00", "Acceso a brazos robóticos de 6 grados de libertad, cámaras industriales y bandas transportadoras."),
            ("Reserva Laboratorio Realidad Virtual y Captura Movimiento", "2950.00", "Espacio equipado con visores VR empresariales, estaciones RTX y sistema de tracking espacial."),
            ("Acceso Remoto Granja de Cómputo HPC (40 Horas Nodo)", "2200.00", "Asignación de tiempo de cómputo paralelo para simulaciones numéricas y procesamiento masivo."),
            ("Uso Cámara Anecoica y Pruebas de Radiofrecuencia", "4200.00", "Medición de patrones de radiación, interferencia electromagnética y caracterización de antenas."),
            ("Sesión Laboratorio Automatización PLC y Redes Industriales", "2400.00", "Prácticas con controladores lógicos programables, HMI táctiles y protocolos Modbus/Profinet."),
            ("Uso Estudio Grabación Multimedia y Streaming Académico", "1750.00", "Cabina insonorizada con iluminación LED, switcher HDMI multicámara y consola de audio digital."),
            ("Laboratorio Pruebas Usabilidad y Accesibilidad Web (UX)", "1550.00", "Sala con cámara de observación, rastreo ocular básico y grabación de sesiones con usuarios."),
            ("Uso Banco de Pruebas Energías Renovables y Fotovoltaica", "2700.00", "Módulo experimental con inversores híbridos, analizador de calidad de energía y paneles solares."),
            ("Acceso Laboratorio Metrología Dimensional y Calibración", "2150.00", "Verificación de tolerancias geométricas con máquina de medición por coordenadas y rugosímetro."),
        ],
    ),
    (
        "Certificaciones Oficiales",
        "86111600",
        "ACT",
        "Examen Supervisado / Voucher Oficial",
        "Centro Evaluador y Certificador UTEZ",
        "Entrega de voucher oficial en máximo 48 horas hábiles",
        "Lunes a Viernes 09:00 - 17:00",
        [
            ("Voucher Examen Certificación AWS Certified Cloud Practitioner", "2150.00", "Derecho a examen oficial en línea o centro evaluador con guía de estudio institucional."),
            ("Voucher Examen Certificación AWS Solutions Architect Associate", "3200.00", "Evaluación oficial de arquitectura en la nube AWS con simulador previo de práctica."),
            ("Certificación Oracle Database SQL Certified Associate", "3800.00", "Voucher oficial Oracle University para acreditar dominio de consultas, DDL y modelado SQL."),
            ("Certificación Scrum Master Professional (SMPC)", "2500.00", "Evaluación internacional en español con dos intentos incluidos y credencial digital verificable."),
            ("Voucher Certificación Python Institute PCAP Associate", "2950.00", "Acreditación oficial en programación orientada a objetos, módulos y manejo de excepciones."),
            ("Certificación Cisco CCNA Switching, Routing & Wireless", "6200.00", "Voucher oficial para examen de redes empresariales, direccionamiento IPv6 y seguridad básica."),
            ("Certificación CompTIA Security+ (Academic Voucher)", "4900.00", "Acreditación global en fundamentos de ciberseguridad, gestión de riesgos y criptografía."),
            ("Certificación Microsoft Azure Fundamentals (AZ-900)", "1950.00", "Voucher oficial de evaluación en conceptos de nube, gobernanza y servicios core de Azure."),
            ("Certificación ISTQB Foundation Level Testing QA", "3950.00", "Examen oficial en aseguramiento de calidad de software, diseño de pruebas y ciclo de vida."),
            ("Certificación Linux Professional Institute LPIC-1", "3600.00", "Voucher para evaluación de administración de sistemas GNU/Linux, systemd y redes."),
            ("Certificación Gestión de Servicios ITIL 4 Foundation", "4400.00", "Examen internacional de mejores prácticas en mesa de servicio, incidentes y mejora continua."),
            ("Certificación Desarrollo Web Accesible W3C / WCAG 2.2", "2750.00", "Evaluación práctica de cumplimiento de estándares de accesibilidad nivel AA en aplicaciones web."),
            ("Certificación Ciencia de Datos e IA Aplicada Nivel Inicial", "3100.00", "Evaluación teórico-práctica sobre limpieza de datos, regresión, clasificación y ética en IA."),
            ("Evaluación Competencias Laborales CONOCER Estándar TIC", "2300.00", "Proceso oficial de alineación y evaluación de competencias ante entidad certificadora nacional."),
        ],
    ),
    (
        "Soporte Técnico",
        "81111800",
        "E48",
        "Mesa de Ayuda / En Sitio",
        "Departamento de Soporte y Mantenimiento TIC",
        "Tiempo de primera respuesta < 2 horas hábiles",
        "Lunes a Viernes 08:00 - 20:00",
        [
            ("Póliza Mensual Mesa de Ayuda Nivel 1 y 2 (Hasta 50 Equipos)", "4500.00", "Atención de incidencias de software, red, impresoras y cuentas institucionales vía ticket."),
            ("Mantenimiento Preventivo y Limpieza Estación de Trabajo", "450.00", "Limpieza interna, cambio de pasta térmica, actualización de BIOS y optimización de sistema operativo."),
            ("Configuración y Endurecimiento Servidor Linux Ubuntu/RHEL", "2200.00", "Instalación de firewall UFW, fail2ban, SSH por llave pública, Nginx y políticas de auditoría."),
            ("Migración Segura de Base de Datos y Pruebas de Integridad", "3800.00", "Extracción, transformación, validación de llaves foráneas y verificación de procedimientos almacenados."),
            ("Diagnóstico y Recuperación Lógica de Almacenamiento", "1850.00", "Análisis de sectores, clonación forense segura y recuperación de archivos en unidades dañadas."),
            ("Soporte Especializado Videoconferencia y Aulas Híbridas", "1300.00", "Calibración de audio, cámaras PTZ, pizarras interactivas y enlaces de transmisión institucional."),
            ("Cableado Estructurado Cat6A Certificación Fluke (Por Nodo)", "980.00", "Instalación, ponchado, etiquetado normativo TIA-568 y entrega de reporte de certificación."),
            ("Configuración Access Points Empresariales y Controladora Wi-Fi", "1950.00", "Despliegue de redes VLAN separadas para docentes, alumnos e invitados con portal cautivo."),
            ("Atención Urgente Incidentes Seguridad y Contención Malware", "3900.00", "Aislamiento de equipo comprometido, análisis de bitácoras, rotación de credenciales y remediación."),
            ("Actualización Firmware Switches Gestionables y Respaldo Config", "1650.00", "Ventana programada de parcheo de equipos de núcleo, respaldo de running-config y rollback."),
            ("Calibración y Mantenimiento Impresoras 3D y Plotter Campus", "1150.00", "Nivelación de cama, reemplazo de boquillas, lubricación de guías y ajuste de extrusor."),
            ("Administración Mensual Backups y Verificación de Restore", "2400.00", "Supervisión diaria de tareas de respaldo, alertas de fallo y simulacro mensual de recuperación."),
            ("Despliegue Masivo Imágenes Sistema Operativo PXE/MDM", "2750.00", "Estandarización de paquetería académica en laboratorios completos mediante arranque en red."),
            ("Soporte Técnico Evento Académico / Congreso (Jornada 8 Horas)", "2100.00", "Técnico dedicado en sitio para audio, proyección, red inalámbrica y respaldo en vivo."),
        ],
    ),
    (
        "Capacitación Especializada",
        "86111500",
        "ACT",
        "Presencial / Virtual Síncrono",
        "Educación Continua y Vinculación Tecnológica",
        "Constancia oficial emitida en 5 días hábiles",
        "Lunes a Sábado según programación académica",
        [
            ("Curso Taller Desarrollo APIs REST Seguras con Python Flask", "3400.00", "Capacitación práctica de 24 horas en arquitectura modular, DTOs Pydantic, JWT RS256 y despliegue."),
            ("Diplomado Arquitectura en la Nube AWS para Desarrolladores", "6800.00", "Programa intensivo de 48 horas cubriendo IAM, VPC, EC2, RDS, DynamoDB, S3 y buenas prácticas."),
            ("Taller Administración Oracle Database y PL/SQL Avanzado", "4200.00", "Entrenamiento de 30 horas en diseño relacional, cursores, transacciones atómicas y optimización."),
            ("Curso Ciberseguridad Defensiva y OWASP Top 10 (20 Horas)", "3600.00", "Prevención práctica de inyección SQL, XSS, Mass Assignment, hardening Nginx y auditoría."),
            ("Taller Contenedores Docker y Despliegue Continuo CI/CD", "3100.00", "Automatización de builds, pruebas unitarias con pytest y pipelines reproducibles con GitHub Actions."),
            ("Curso Frontend Moderno con Vite, ES Modules y Fetch Seguro", "2900.00", "Construcción de SPAs sin frameworks pesados, manejo de CSP, CORS y consumo de APIs REST."),
            ("Seminario Facturación Electrónica CFDI 4.0 y Cumplimiento SAT", "2400.00", "Actualización fiscal práctica sobre catálogos SAT, regímenes, complementos de pago y cancelación."),
            ("Taller Análisis de Datos con Python, Pandas y Visualización", "3300.00", "Procesamiento de grandes volúmenes de datos, limpieza estadística y generación de reportes ejecutivos."),
            ("Curso Automatización Industrial con PLC y SCADA Básico", "4500.00", "Programación en diagrama de escalera, comunicación industrial y diseño de pantallas de supervisión."),
            ("Bootcamp Pruebas Automatizadas QA con Pytest y Mocking", "2750.00", "Estrategias de pruebas unitarias, integración, mocks de servicios cloud y cobertura de código."),
            ("Taller Gestión de Proyectos Tecnológicos con Scrum y Kanban", "2600.00", "Dinámicas prácticas de estimación, refinamiento de backlog, métricas de flujo y retrospectivas."),
            ("Curso Diseño de Interfaces UI/UX Centrado en el Usuario", "2850.00", "Prototipado en Figma, sistemas de diseño corporativos, heurísticas de usabilidad y pruebas."),
            ("Seminario Protección de Datos Personales y Cumplimiento LFPDPPP", "2200.00", "Lineamientos legales y técnicos para avisos de privacidad, cifrado y control de acceso."),
            ("Taller Machine Learning Aplicado a Predicción Empresarial", "4100.00", "Implementación de modelos supervisados, validación cruzada y despliegue de inferencia vía API."),
        ],
    ),
    (
        "Consultoría Tecnológica",
        "80101500",
        "E48",
        "Entregable Documental y Sesiones",
        "Centro de Innovación y Consultoría Digital UTEZ",
        "Entrega de informe técnico en plazo pactado por SOW",
        "Lunes a Viernes 09:00 - 18:00",
        [
            ("Auditoría Integral de Seguridad en Aplicaciones Web (OWASP)", "8500.00", "Evaluación exhaustiva de APIs y frontend con pruebas controladas y plan priorizado de remediación."),
            ("Diseño de Arquitectura Cloud Alta Disponibilidad en AWS", "7200.00", "Levantamiento de requerimientos, diagramas de red VPC, estimación de costos y hoja de ruta."),
            ("Consultoría Optimización de Consultas y Esquemas Oracle RDS", "6400.00", "Análisis de planes de ejecución, índices faltantes, bloqueos de concurrencia y refactor PL/SQL."),
            ("Diagnóstico de Madurez Digital para PyMEs Regionales", "4900.00", "Evaluación de procesos operativos, sistemas actuales y recomendaciones tecnológicas de alto impacto."),
            ("Asesoría Migración de Monolitos a Servicios Modulares REST", "6900.00", "Definición de contratos OpenAPI, desacoplamiento por capas y estrategia de transición sin caídas."),
            ("Consultoría Implementación Gobierno de Datos y Catálogos", "5800.00", "Estandarización de diccionarios de datos, trazabilidad de bitácoras y políticas de retención."),
            ("Evaluación de Rendimiento y Pruebas de Estrés HTTP (Load Test)", "5200.00", "Simulación de concurrencia con métricas p95/p99, dimensionamiento de workers Gunicorn y Nginx."),
            ("Acompañamiento Técnico Certificación Accesibilidad Web AA", "4300.00", "Revisión línea por línea de contraste, navegación por teclado, ARIA y cumplimiento normativo."),
            ("Consultoría Continuidad de Negocio (BCP) y Plan DRP", "7600.00", "Definición de objetivos RPO/RTO, matriz de riesgos críticos y protocolo documentado de recuperación."),
            ("Asesoría Integración Pasarelas de Pago y Facturación CFDI", "6100.00", "Diseño de flujos idempotentes, conciliación de webhooks, almacenamiento S3 y auditoría fiscal."),
            ("Consultoría Automatización de Reportes Gerenciales BI", "4700.00", "Modelado de KPIs financieros y operativos conectados a fuentes relacionales y NoSQL."),
            ("Revisión Arquitectura IAM y Principio de Mínimo Privilegio", "5400.00", "Auditoría de roles, políticas, rotación de secretos, Cognito JWKS y cifrado en tránsito."),
            ("Consultoría Desarrollo de Software Seguro (SSDLC)", "6300.00", "Integración de análisis estático, gestión de dependencias y checklist de seguridad en CI/CD."),
            ("Estudio de Factibilidad Técnica y Retorno de Inversión TI", "4600.00", "Análisis comparativo TCO on-premise vs nube con proyección financiera a 36 meses."),
        ],
    ),
]


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _build_50_characteristics(
    sku: str,
    nombre: str,
    categoria: str,
    precio: Decimal,
    clave_sat: str,
    unidad_sat: str,
    modalidad: str,
    area_utez: str,
    sla: str,
    horario: str,
) -> dict[str, str]:
    iva = _round_money(precio * Decimal("0.16"))
    total_iva = _round_money(precio + iva)

    values: list[str] = [
        # 01..12: Fiscal y legal
        f"Clave SAT {clave_sat}",
        f"Unidad de medida SAT {unidad_sat}",
        "Tasa IVA trasladado 16.00% (002)",
        "Objeto de impuesto: 02 - Sí objeto de impuesto",
        "Retención ISR / IVA: No aplica",
        "Comprobante fiscal CFDI 4.0 válido en México",
        "Uso CFDI sugerido: G03 - Gastos en general",
        "Moneda oficial de emisión: MXN",
        "Régimen emisor institucional UTEZ (603)",
        "Trazabilidad obligatoria en bitácora Oracle RDS",
        "Cumplimiento normativo LFPDPPP y Código Fiscal",
        "Resguardo digital XML/PDF en S3 privado cifrado",
        # 13..22: Identificación
        sku,
        nombre,
        categoria,
        area_utez,
        modalidad,
        "Catálogo Oficial Servicios UTEZ 2026.1",
        f"Código contable interno UTEZ-{sku}",
        "Cobertura: Campus Emiliano Zapata y modalidad remota",
        "Clasificación: Servicio Tecnológico Universitario",
        "Estado del registro en catálogo: Activo",
        # 23..32: Comercial
        f"Precio unitario base sin IVA: ${precio:,.2f} MXN",
        f"IVA unitario calculado (16%): ${iva:,.2f} MXN",
        f"Importe unitario total con IVA: ${total_iva:,.2f} MXN",
        "Descuento institucional aplicable bajo convenio",
        "Unidad comercial: Por servicio / periodo contratado",
        "Facturación disponible en pago PUE o PPD",
        "Formas de pago habilitadas: 01, 03, 04, 28",
        "Vigencia de cotización oficial: 30 días naturales",
        "Política de cancelación: Sujeta a validación fiscal CFDI",
        "Canal de contratación: Portal de Facturación UTEZ",
        # 33..41: Contractual
        sla,
        "Acuerdo de confidencialidad y no divulgación (NDA)",
        "Entregable formal: Constancia o comprobante digital",
        "Requisito previo: Datos fiscales vigentes del receptor",
        "Responsabilidad limitada al alcance del servicio",
        "Propiedad intelectual reservada al titular licenciado",
        "Penalización por incumplimiento sujeta a convenio",
        "Criterio de aceptación: Validación técnica del solicitante",
        "Renovación previa confirmación administrativa",
        # 42..50: Operativa
        "Aprovisionamiento estimado: 24 a 72 horas hábiles",
        horario,
        "Mesa de servicio: soporte.tic@utez.edu.mx",
        "Entorno operativo: Infraestructura AWS / Campus UTEZ",
        "Requisito técnico: Cuenta institucional verificada",
        "Mantenimiento preventivo y respaldos programados",
        "Monitoreo continuo de disponibilidad y bitácoras",
        "Escalamiento técnico N1 -> N2 -> DTI UTEZ",
        f"Responsable operativo: {area_utez}",
    ]

    if len(values) != 50:
        raise RuntimeError(f"Expected 50 characteristics for {sku}, got {len(values)}")

    return {f"caracteristica_{idx:02d}": val for idx, val in enumerate(values, start=1)}


def build_realistic_services() -> list[dict[str, Any]]:
    """Build 100 distinct realistic services preserving SKUs SRV-001..SRV-100."""
    items: list[dict[str, Any]] = []
    counter = 1

    for (
        categoria,
        clave_sat,
        unidad_sat,
        modalidad,
        area_utez,
        sla,
        horario,
        servicios,
    ) in _CATALOG_SPEC:
        for nombre, raw_price, descripcion in servicios:
            sku = f"SRV-{counter:03d}"
            precio = _round_money(Decimal(raw_price))
            item: dict[str, Any] = {
                "id_service": sku,
                "nombre_servicio": nombre,
                "categoria": categoria,
                "precio_unitario": precio,
                "descripcion": descripcion,
                "caracteristicas": _build_50_characteristics(
                    sku=sku,
                    nombre=nombre,
                    categoria=categoria,
                    precio=precio,
                    clave_sat=clave_sat,
                    unidad_sat=unidad_sat,
                    modalidad=modalidad,
                    area_utez=area_utez,
                    sla=sla,
                    horario=horario,
                ),
            }
            # Validate compatibility with backend DTO contract
            build_servicio_detalle(item)
            items.append(item)
            counter += 1

    if len(items) != 100:
        raise RuntimeError(f"Expected 100 services, generated {len(items)}")

    unique_names = {item["nombre_servicio"] for item in items}
    if len(unique_names) != 100:
        raise RuntimeError("Duplicate service names detected in seed catalog")

    return items


def seed_dynamodb(
    items: list[dict[str, Any]],
    table_name: str,
    region_name: str,
) -> None:
    """Write all 100 items to DynamoDB ListServices using batch_writer."""
    dynamodb = boto3.resource(
        "dynamodb",
        region_name=region_name,
        config=get_boto3_config(),
    )
    table = dynamodb.Table(table_name)
    with table.batch_writer(overwrite_by_pkeys=["id_service"]) as batch:
        for item in items:
            batch.put_item(Item=item)


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Sobrescribe los 100 servicios de ListServices con un catálogo realista."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Genera y valida los 100 servicios localmente sin escribir en DynamoDB.",
    )
    args = parser.parse_args()

    region = os.getenv("AWS_REGION", "us-east-1").strip() or "us-east-1"
    table_name = os.getenv("DYNAMO_TABLE_SERVICES", "ListServices").strip() or "ListServices"

    items = build_realistic_services()
    print(f"Generados y validados {len(items)} servicios únicos (SRV-001..SRV-100).")

    if args.dry_run:
        sample = items[0]
        print(
            f"[DRY-RUN] Ejemplo {sample['id_service']}: "
            f"{sample['nombre_servicio']} | {sample['categoria']} | "
            f"${sample['precio_unitario']} | {len(sample['caracteristicas'])} características."
        )
        return 0

    seed_dynamodb(items=items, table_name=table_name, region_name=region)
    print(f"Cargados {len(items)} servicios en DynamoDB tabla '{table_name}' ({region}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
