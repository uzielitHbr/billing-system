from __future__ import annotations

import os
from dataclasses import dataclass

from botocore.config import Config
from dotenv import load_dotenv

DEFAULT_CORS_ORIGINS = (
    "http://billing-frontend-utez.s3-website-us-east-1.amazonaws.com,"
    "http://localhost:5173"
)

REQUIRED_PRODUCTION_VARS = (
    "AWS_REGION",
    "COGNITO_USER_POOL_ID",
    "COGNITO_CLIENT_ID",
    "DYNAMO_TABLE_SERVICES",
    "S3_BUCKET_COMPROBANTES",
    "ORACLE_USER",
    "ORACLE_PASSWORD",
    "ORACLE_DSN",
    "CORS_ALLOWED_ORIGINS",
)


def parse_cors_origins(raw_origins: str | list[str] | None) -> list[str]:
    """Parse comma-separated CORS origins into a cleaned list of strings."""
    if raw_origins is None:
        return []
    if isinstance(raw_origins, list):
        return [origin.strip() for origin in raw_origins if str(origin).strip()]
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


@dataclass(frozen=True)
class Settings:
    """Application settings loaded and validated from environment variables."""

    FLASK_ENV: str
    AWS_REGION: str
    COGNITO_USER_POOL_ID: str
    COGNITO_CLIENT_ID: str
    DYNAMO_TABLE_SERVICES: str
    S3_BUCKET_COMPROBANTES: str
    ORACLE_USER: str
    ORACLE_PASSWORD: str
    ORACLE_DSN: str
    CORS_ALLOWED_ORIGINS: list[str]
    TESTING: bool = False

    @property
    def is_production(self) -> bool:
        return self.FLASK_ENV.lower() == "production"

    def validate(self) -> None:
        """Validate that all required environment variables are present in production."""
        if not self.is_production:
            return

        missing = [
            var_name
            for var_name in REQUIRED_PRODUCTION_VARS
            if not getattr(self, var_name)
        ]
        if missing:
            raise ValueError(
                "Faltan variables de entorno requeridas en producción: "
                + ", ".join(missing)
            )

    @classmethod
    def from_env(cls, load_env_file: bool = True) -> Settings:
        """Build and validate Settings from the current environment."""
        if load_env_file:
            load_dotenv()

        flask_env = os.getenv("FLASK_ENV", "development").strip() or "development"
        is_prod = flask_env.lower() == "production"

        raw_cors = os.getenv("CORS_ALLOWED_ORIGINS")
        if raw_cors is None and not is_prod:
            raw_cors = DEFAULT_CORS_ORIGINS

        settings = cls(
            FLASK_ENV=flask_env,
            AWS_REGION=os.getenv("AWS_REGION", "" if is_prod else "us-east-1").strip(),
            COGNITO_USER_POOL_ID=os.getenv("COGNITO_USER_POOL_ID", "").strip(),
            COGNITO_CLIENT_ID=os.getenv("COGNITO_CLIENT_ID", "").strip(),
            DYNAMO_TABLE_SERVICES=os.getenv(
                "DYNAMO_TABLE_SERVICES", "" if is_prod else "ListServices"
            ).strip(),
            S3_BUCKET_COMPROBANTES=os.getenv("S3_BUCKET_COMPROBANTES", "").strip(),
            ORACLE_USER=os.getenv("ORACLE_USER", "").strip(),
            ORACLE_PASSWORD=os.getenv("ORACLE_PASSWORD", "").strip(),
            ORACLE_DSN=os.getenv("ORACLE_DSN", "").strip(),
            CORS_ALLOWED_ORIGINS=parse_cors_origins(raw_cors),
            TESTING=flask_env.lower() == "testing",
        )
        settings.validate()
        return settings


def get_boto3_config(
    connect_timeout: int = 5,
    read_timeout: int = 15,
    max_attempts: int = 2,
) -> Config:
    """Return explicit botocore timeouts to prevent Gunicorn worker hangs."""
    return Config(
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        retries={"max_attempts": max_attempts, "mode": "standard"},
    )
