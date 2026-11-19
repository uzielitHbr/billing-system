-- ============================================================================
-- ARCHIVO: sql/02_stored_procedures.sql — LOS 10 PROCEDIMIENTOS ALMACENADOS
-- ============================================================================

-- 1. AUDITORIA CENTRALIZADA
CREATE OR REPLACE PROCEDURE SP_REGISTRAR_BITACORA (
    p_id_factura  IN NUMBER,
    p_accion      IN VARCHAR2,
    p_descripcion IN VARCHAR2,
    p_ip_origen   IN VARCHAR2,
    p_usuario     IN VARCHAR2
) AS
BEGIN
    INSERT INTO bitacora_facturacion (id_factura, accion, descripcion, ip_origen, usuario)
    VALUES (p_id_factura, p_accion, SUBSTR(p_descripcion, 1, 400), p_ip_origen, NVL(p_usuario, USER));
END SP_REGISTRAR_BITACORA;
/

-- 2. SINCRONIZACION DE USUARIO AUTENTICADO CON AMAZON COGNITO
CREATE OR REPLACE PROCEDURE SP_SINCRONIZAR_USUARIO_COGNITO (
    p_cognito_sub IN  VARCHAR2,
    p_email       IN  VARCHAR2,
    p_nombre      IN  VARCHAR2,
    p_id_usuario  OUT NUMBER,
    p_rol         OUT VARCHAR2,
    p_activo      OUT NUMBER
) AS
    v_count NUMBER;
BEGIN
    SELECT id_usuario, rol, activo
      INTO p_id_usuario, p_rol, p_activo
      FROM usuarios
     WHERE cognito_sub = p_cognito_sub;

    UPDATE usuarios
       SET email = LOWER(TRIM(p_email)),
           ultimo_acceso = SYSTIMESTAMP
     WHERE id_usuario = p_id_usuario;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        SELECT COUNT(*) INTO v_count FROM usuarios;
        p_rol := CASE WHEN v_count = 0 THEN 'ADMIN_ACADEMICO' ELSE 'FACTURADOR' END;
        p_activo := 1;
        INSERT INTO usuarios (cognito_sub, email, nombre, rol, activo)
        VALUES (p_cognito_sub, LOWER(TRIM(p_email)), NVL(NULLIF(TRIM(p_nombre), ''), p_email), p_rol, 1)
        RETURNING id_usuario INTO p_id_usuario;
END SP_SINCRONIZAR_USUARIO_COGNITO;
/

-- 3. CONSULTA DE LOS 4 CATALOGOS SAT ACTIVOS
CREATE OR REPLACE PROCEDURE SP_LISTAR_CATALOGOS_SAT (
    p_cur_formas    OUT SYS_REFCURSOR,
    p_cur_metodos   OUT SYS_REFCURSOR,
    p_cur_regimenes OUT SYS_REFCURSOR,
    p_cur_usos      OUT SYS_REFCURSOR
) AS
BEGIN
    OPEN p_cur_formas FOR
        SELECT id_forma_pago AS clave, descripcion FROM cat_forma_pago WHERE activo = 1 ORDER BY id_forma_pago;
    OPEN p_cur_metodos FOR
        SELECT id_metodo_pago AS clave, descripcion FROM cat_metodo_pago WHERE activo = 1 ORDER BY id_metodo_pago;
    OPEN p_cur_regimenes FOR
        SELECT id_regimen_fiscal AS clave, descripcion, aplica_fisica, aplica_moral
          FROM cat_regimen_fiscal WHERE activo = 1 ORDER BY id_regimen_fiscal;
    OPEN p_cur_usos FOR
        SELECT id_uso_cfdi AS clave, descripcion FROM cat_uso_cfdi WHERE activo = 1 ORDER BY id_uso_cfdi;
END SP_LISTAR_CATALOGOS_SAT;
/

-- 4. ALTA O ACTUALIZACION DE CLIENTE POR RFC UNICO
CREATE OR REPLACE PROCEDURE SP_UPSERT_CLIENTE (
    p_rfc          IN  VARCHAR2,
    p_razon_social IN  VARCHAR2,
    p_cp           IN  VARCHAR2,
    p_regimen      IN  VARCHAR2,
    p_uso_cfdi     IN  VARCHAR2,
    p_email        IN  VARCHAR2,
    p_id_cliente   OUT NUMBER
) AS
    v_rfc VARCHAR2(13) := UPPER(TRIM(p_rfc));
BEGIN
    SELECT id_cliente INTO p_id_cliente FROM clientes WHERE rfc = v_rfc;
    UPDATE clientes
       SET razon_social      = TRIM(p_razon_social),
           codigo_postal     = TRIM(p_cp),
           id_regimen_fiscal = TRIM(p_regimen),
           id_uso_cfdi       = TRIM(p_uso_cfdi),
           email             = LOWER(TRIM(p_email))
     WHERE id_cliente = p_id_cliente;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        INSERT INTO clientes (rfc, razon_social, codigo_postal, id_regimen_fiscal, id_uso_cfdi, email)
        VALUES (v_rfc, TRIM(p_razon_social), TRIM(p_cp), TRIM(p_regimen), TRIM(p_uso_cfdi), LOWER(TRIM(p_email)))
        RETURNING id_cliente INTO p_id_cliente;
END SP_UPSERT_CLIENTE;
/

-- 5. CREACION DE CABECERA DE FACTURA EN ESTADO PENDIENTE
CREATE OR REPLACE PROCEDURE SP_CREAR_FACTURA_BORRADOR (
    p_rfc_emisor  IN  VARCHAR2,
    p_id_cliente  IN  NUMBER,
    p_id_usuario  IN  NUMBER,
    p_forma_pago  IN  VARCHAR2,
    p_metodo_pago IN  VARCHAR2,
    p_direccion   IN  VARCHAR2,
    p_comentarios IN  VARCHAR2,
    p_id_factura  OUT NUMBER,
    p_folio       OUT NUMBER
) AS
BEGIN
    SELECT seq_folio_factura.NEXTVAL INTO p_folio FROM DUAL;
    INSERT INTO facturas (
        serie, folio, rfc_emisor, id_cliente, id_usuario_creador,
        id_forma_pago, id_metodo_pago, direccion_fiscal, comentarios, estado
    ) VALUES (
        'A', p_folio, UPPER(TRIM(p_rfc_emisor)), p_id_cliente, p_id_usuario,
        TRIM(p_forma_pago), TRIM(p_metodo_pago), TRIM(p_direccion), p_comentarios, 'PENDIENTE'
    ) RETURNING id_factura INTO p_id_factura;
END SP_CREAR_FACTURA_BORRADOR;
/

-- 6. INSERCION DE RENGLON + CALCULO AUTOMATICO DE IVA 16%
CREATE OR REPLACE PROCEDURE SP_AGREGAR_DETALLE_FACTURA (
    p_id_factura         IN  NUMBER,
    p_id_servicio_dynamo IN  VARCHAR2,
    p_descripcion        IN  VARCHAR2,
    p_cantidad           IN  NUMBER,
    p_precio_unitario    IN  NUMBER,
    p_id_detalle         OUT NUMBER
) AS
    v_importe NUMBER(14,2);
    v_iva     NUMBER(14,2);
BEGIN
    v_importe := ROUND(p_cantidad * p_precio_unitario, 2);
    v_iva     := ROUND(v_importe * 0.16, 2);

    INSERT INTO factura_detalles (
        id_factura, id_servicio_dynamo, descripcion_item, cantidad, precio_unitario, importe
    ) VALUES (
        p_id_factura, TRIM(p_id_servicio_dynamo), TRIM(p_descripcion), p_cantidad, p_precio_unitario, v_importe
    ) RETURNING id_detalle INTO p_id_detalle;

    INSERT INTO factura_impuestos (id_detalle, impuesto, tipo_factor, tasa_cuota, base, importe)
    VALUES (p_id_detalle, '002', 'Tasa', 0.1600, v_importe, v_iva);
END SP_AGREGAR_DETALLE_FACTURA;
/

-- 7. RECALCULO DE SUBTOTAL, IMPUESTOS Y TOTAL EN CABECERA
CREATE OR REPLACE PROCEDURE SP_RECALCULAR_TOTALES_FACTURA (
    p_id_factura IN  NUMBER,
    p_subtotal   OUT NUMBER,
    p_impuestos  OUT NUMBER,
    p_total      OUT NUMBER
) AS
BEGIN
    SELECT NVL(SUM(importe), 0) INTO p_subtotal
      FROM factura_detalles
     WHERE id_factura = p_id_factura;

    SELECT NVL(SUM(fi.importe), 0) INTO p_impuestos
      FROM factura_impuestos fi
      JOIN factura_detalles fd ON fd.id_detalle = fi.id_detalle
     WHERE fd.id_factura = p_id_factura;

    p_total := ROUND(p_subtotal + p_impuestos, 2);

    UPDATE facturas
       SET subtotal        = p_subtotal,
           total_impuestos = p_impuestos,
           total           = p_total
     WHERE id_factura = p_id_factura;
END SP_RECALCULAR_TOTALES_FACTURA;
/

-- 8. TIMBRADO / EMISION OFICIAL CON UUID Y BLOQUEO DE CONCURRENCIA
CREATE OR REPLACE PROCEDURE SP_TIMBRAR_FACTURA (
    p_id_factura     IN  NUMBER,
    p_uuid           IN  VARCHAR2,
    p_folio          OUT NUMBER,
    p_serie          OUT VARCHAR2,
    p_fecha_timbrado OUT TIMESTAMP
) AS
    v_estado VARCHAR2(20);
BEGIN
    SELECT estado, folio, serie
      INTO v_estado, p_folio, p_serie
      FROM facturas
     WHERE id_factura = p_id_factura
       FOR UPDATE WAIT 5;

    IF v_estado <> 'PENDIENTE' THEN
        RAISE_APPLICATION_ERROR(-20001, 'Solo se pueden timbrar facturas en estado PENDIENTE. Estado actual: ' || v_estado);
    END IF;

    p_fecha_timbrado := SYSTIMESTAMP;

    UPDATE facturas
       SET folio_fiscal_uuid = p_uuid,
           estado            = 'TIMBRADA',
           fecha_timbrado    = p_fecha_timbrado
     WHERE id_factura = p_id_factura;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RAISE_APPLICATION_ERROR(-20004, 'Factura no encontrada: ' || p_id_factura);
    WHEN OTHERS THEN
        IF SQLCODE IN (-54, -30006) THEN
            RAISE_APPLICATION_ERROR(-20003, 'Factura bloqueada por otra transacción en curso: ' || p_id_factura);
        END IF;
        RAISE;
END SP_TIMBRAR_FACTURA;
/

-- 9. CANCELACION AUDITADA DE FACTURA TIMBRADA
CREATE OR REPLACE PROCEDURE SP_CANCELAR_FACTURA (
    p_id_factura IN NUMBER,
    p_motivo     IN VARCHAR2,
    p_usuario    IN VARCHAR2,
    p_ip_origen  IN VARCHAR2
) AS
    v_estado VARCHAR2(20);
BEGIN
    SELECT estado INTO v_estado
      FROM facturas
     WHERE id_factura = p_id_factura
       FOR UPDATE WAIT 5;

    IF v_estado <> 'TIMBRADA' THEN
        RAISE_APPLICATION_ERROR(-20002, 'Solo se pueden cancelar facturas en estado TIMBRADA. Estado actual: ' || v_estado);
    END IF;

    UPDATE facturas
       SET estado = 'CANCELADA'
     WHERE id_factura = p_id_factura;

    SP_REGISTRAR_BITACORA(p_id_factura, 'CANCELACION', 'Motivo: ' || p_motivo, p_ip_origen, p_usuario);
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RAISE_APPLICATION_ERROR(-20004, 'Factura no encontrada: ' || p_id_factura);
    WHEN OTHERS THEN
        IF SQLCODE IN (-54, -30006) THEN
            RAISE_APPLICATION_ERROR(-20003, 'Factura bloqueada por otra transacción en curso: ' || p_id_factura);
        END IF;
        RAISE;
END SP_CANCELAR_FACTURA;
/

-- 10. CONSULTA INTEGRAL DE FACTURA (PARA RESPUESTA JSON, PDF Y XML)
CREATE OR REPLACE PROCEDURE SP_CONSULTAR_FACTURA_COMPLETA (
    p_id_factura   IN  NUMBER,
    p_cur_cabecera OUT SYS_REFCURSOR,
    p_cur_detalles OUT SYS_REFCURSOR
) AS
BEGIN
    OPEN p_cur_cabecera FOR
        SELECT f.id_factura, f.folio_fiscal_uuid, f.serie, f.folio, f.rfc_emisor,
               f.direccion_fiscal, f.comentarios, f.subtotal, f.total_impuestos,
               f.total, f.moneda, f.estado, f.fecha_emision, f.fecha_timbrado,
               c.rfc AS rfc_receptor, c.razon_social, c.codigo_postal, c.email AS email_receptor,
               c.id_regimen_fiscal, rf.descripcion AS regimen_descripcion,
               c.id_uso_cfdi, uc.descripcion AS uso_cfdi_descripcion,
               f.id_forma_pago, fp.descripcion AS forma_pago_descripcion,
               f.id_metodo_pago, mp.descripcion AS metodo_pago_descripcion,
               u.email AS usuario_creador
          FROM facturas f
          JOIN clientes c            ON c.id_cliente        = f.id_cliente
          JOIN usuarios u            ON u.id_usuario        = f.id_usuario_creador
          JOIN cat_regimen_fiscal rf ON rf.id_regimen_fiscal = c.id_regimen_fiscal
          JOIN cat_uso_cfdi uc       ON uc.id_uso_cfdi       = c.id_uso_cfdi
          JOIN cat_forma_pago fp     ON fp.id_forma_pago     = f.id_forma_pago
          JOIN cat_metodo_pago mp    ON mp.id_metodo_pago    = f.id_metodo_pago
         WHERE f.id_factura = p_id_factura;

    OPEN p_cur_detalles FOR
        SELECT fd.id_detalle, fd.id_servicio_dynamo AS sku, fd.descripcion_item,
               fd.clave_sat_producto, fd.clave_sat_unidad, fd.cantidad,
               fd.precio_unitario, fd.importe, fd.descuento,
               NVL(fi.tasa_cuota, 0.16) AS tasa_iva, NVL(fi.importe, 0) AS importe_iva
          FROM factura_detalles fd
          LEFT JOIN factura_impuestos fi ON fi.id_detalle = fd.id_detalle
         WHERE fd.id_factura = p_id_factura
         ORDER BY fd.id_detalle ASC;
END SP_CONSULTAR_FACTURA_COMPLETA;
/
