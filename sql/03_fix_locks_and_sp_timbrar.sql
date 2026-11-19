-- ============================================================================
-- ARCHIVO: sql/03_fix_locks_and_sp_timbrar.sql
-- EJECUTAR EN ORACLE RDS (db-billing-system / ORCL) PARA EVITAR LOCKS INFINITOS
-- ============================================================================
-- 1) Asegura que SP_REGISTRAR_BITACORA NO use PRAGMA AUTONOMOUS_TRANSACTION
--    (evita interbloqueos por FK fk_bit_factura sobre facturas no confirmadas).
-- 2) Agrega FOR UPDATE WAIT 5 a SP_TIMBRAR_FACTURA y SP_CANCELAR_FACTURA
--    y traduce ORA-00054 / ORA-30006 a ORA-20003 (HTTP 409) en lugar de
--    bloquear al worker de Gunicorn durante 60 segundos.

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
