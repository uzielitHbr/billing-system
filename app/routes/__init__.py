from app.routes.auth_routes import auth_bp
from app.routes.catalog_routes import catalog_bp
from app.routes.factura_routes import factura_bp
from app.routes.health_routes import health_bp

__all__ = ["health_bp", "auth_bp", "catalog_bp", "factura_bp"]
