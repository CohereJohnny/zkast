"""Dependency checks for readiness probe."""

from __future__ import annotations

from typing import Any

import psycopg
import redis
from redis.exceptions import RedisError

from app.config import Settings


def _check_postgres(database_url: str) -> dict[str, Any]:
    try:
        with psycopg.connect(database_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 — readiness aggregates errors
        return {"status": "error", "detail": str(exc)[:200]}


def _check_redis(url: str) -> dict[str, Any]:
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=3)
        client.ping()
        return {"status": "ok"}
    except RedisError as exc:
        return {"status": "error", "detail": str(exc)[:200]}


def _check_falkordb(host: str, port: int) -> dict[str, Any]:
    try:
        client = redis.Redis(host=host, port=port, socket_connect_timeout=3)
        client.ping()
        return {"status": "ok"}
    except RedisError as exc:
        return {"status": "error", "detail": str(exc)[:200]}


def readiness_report(settings: Settings) -> dict[str, Any]:
    deps = {
        "postgres": _check_postgres(settings.database_url),
        "redis": _check_redis(settings.redis_url),
        "falkordb": _check_falkordb(settings.falkordb_host, settings.falkordb_port),
    }
    ok = all(d.get("status") == "ok" for d in deps.values())
    return {
        "status": "ok" if ok else "degraded",
        "dependencies": deps,
    }
