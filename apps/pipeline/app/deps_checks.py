"""Dependency checks for readiness probe."""

from __future__ import annotations

from typing import Any

import psycopg
import redis
from redis.exceptions import RedisError

from app.cohere_probe import probe_cohere_sync
from app.config import Settings
from app.workspace_repo import DEFAULT_PIPELINE_SETTINGS


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


def _check_cohere_optional(settings: Settings) -> dict[str, Any]:
    """Cheap provider ping when env bypass key is set; never fails readiness alone."""
    key = settings.cohere_api_key
    if not key:
        return {"status": "skipped", "detail": "COHERE_API_KEY unset (DB workspace keys not probed here)"}
    ok, err = probe_cohere_sync(
        key,
        chat_model=str(DEFAULT_PIPELINE_SETTINGS["large_model"]),
        embed_model=str(DEFAULT_PIPELINE_SETTINGS["embed_model"]),
        rerank_model=str(DEFAULT_PIPELINE_SETTINGS["rerank_model"]),
    )
    if ok:
        return {"status": "ok"}
    return {"status": "error", "detail": err or "unknown"}


def readiness_report(settings: Settings) -> dict[str, Any]:
    deps = {
        "postgres": _check_postgres(settings.database_url),
        "redis": _check_redis(settings.redis_url),
        "falkordb": _check_falkordb(settings.falkordb_host, settings.falkordb_port),
        "cohere": _check_cohere_optional(settings),
    }
    core_ok = all(
        deps[k].get("status") == "ok" for k in ("postgres", "redis", "falkordb")
    )
    return {
        "status": "ok" if core_ok else "degraded",
        "dependencies": deps,
    }
