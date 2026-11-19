from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

import boto3

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_SECONDS = 60.0


class DynamoServiceRepository:
    """Repository for reading the intact DynamoDB ListServices table."""

    def __init__(
        self,
        table_name: str | None = None,
        region_name: str | None = None,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        table: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.table_name = (
            table_name
            or os.getenv("DYNAMO_TABLE_SERVICES", "ListServices").strip()
            or "ListServices"
        )
        self.region_name = (
            region_name or os.getenv("AWS_REGION", "us-east-1").strip() or "us-east-1"
        )
        self.cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock
        self._table = table
        self._lock = threading.Lock()
        self._cache_items: list[dict[str, Any]] | None = None
        self._cache_expires_at: float = 0.0

    def _get_table(self) -> Any:
        if self._table is None:
            with self._lock:
                if self._table is None:
                    resource = boto3.resource("dynamodb", region_name=self.region_name)
                    self._table = resource.Table(self.table_name)
        return self._table

    @staticmethod
    def _normalize_item(item: Mapping[str, Any]) -> dict[str, Any]:
        normalized = dict(item)
        raw_price = normalized.get("precio_unitario")
        if raw_price is not None and not isinstance(raw_price, Decimal):
            normalized["precio_unitario"] = Decimal(str(raw_price))
        return normalized

    def get_service_by_sku(self, sku: str) -> dict[str, Any] | None:
        """Fetch a single service in O(1) via DynamoDB get_item(Key={'id_service': sku})."""
        response = self._get_table().get_item(Key={"id_service": sku})
        item = response.get("Item")
        if not item:
            return None
        return self._normalize_item(item)

    def list_all_services(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """List all services with LastEvaluatedKey pagination and 60s in-memory TTL cache."""
        now = self._clock()
        with self._lock:
            if (
                not force_refresh
                and self._cache_items is not None
                and now < self._cache_expires_at
            ):
                return list(self._cache_items)

        table = self._get_table()
        items: list[dict[str, Any]] = []
        scan_kwargs: dict[str, Any] = {}

        while True:
            response = table.scan(**scan_kwargs)
            for raw_item in response.get("Items", []):
                items.append(self._normalize_item(raw_item))

            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key

        items.sort(key=lambda entry: str(entry.get("id_service", "")))

        with self._lock:
            self._cache_items = items
            self._cache_expires_at = self._clock() + self.cache_ttl_seconds
            return list(self._cache_items)

    def clear_cache(self) -> None:
        """Invalidate the in-memory service list cache."""
        with self._lock:
            self._cache_items = None
            self._cache_expires_at = 0.0

    def check_connection(self) -> bool:
        """Verify DynamoDB ListServices table accessibility for /health."""
        try:
            table = self._get_table()
            response = table.meta.client.describe_table(TableName=self.table_name)
            status = response.get("Table", {}).get("TableStatus")
            return status == "ACTIVE"
        except Exception:
            logger.exception("DynamoDB health check failed for table %s", self.table_name)
            return False


_default_repo: DynamoServiceRepository | None = None
_default_repo_lock = threading.Lock()


def get_dynamo_repo(config: Mapping[str, Any] | None = None) -> DynamoServiceRepository:
    """Return a DynamoServiceRepository configured from app config or environment."""
    global _default_repo
    table_name = (
        str(config["DYNAMO_TABLE_SERVICES"]).strip()
        if config and config.get("DYNAMO_TABLE_SERVICES")
        else os.getenv("DYNAMO_TABLE_SERVICES", "ListServices").strip() or "ListServices"
    )
    region_name = (
        str(config["AWS_REGION"]).strip()
        if config and config.get("AWS_REGION")
        else os.getenv("AWS_REGION", "us-east-1").strip() or "us-east-1"
    )

    with _default_repo_lock:
        if (
            _default_repo is None
            or _default_repo.table_name != table_name
            or _default_repo.region_name != region_name
        ):
            _default_repo = DynamoServiceRepository(
                table_name=table_name,
                region_name=region_name,
            )
        return _default_repo


def get_service_by_sku(
    sku: str, config: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    """Convenience wrapper for O(1) service lookup by SKU."""
    return get_dynamo_repo(config=config).get_service_by_sku(sku)


def list_all_services(
    force_refresh: bool = False,
    config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Convenience wrapper for TTL-cached ListServices listing."""
    return get_dynamo_repo(config=config).list_all_services(force_refresh=force_refresh)


def check_dynamo_connection(config: Mapping[str, Any] | None = None) -> bool:
    """Verify DynamoDB ListServices connectivity for /health."""
    return get_dynamo_repo(config=config).check_connection()
