# zkast migrations (Alembic)

Standalone migration package run as a **one-shot Docker Compose service** (`migrate`) before `pipeline` starts.

## Convention

Every workspace-scoped table added after Sprint 1 **must** include `workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE` and an index on `(workspace_id)` for list queries.

## Environment

- `DATABASE_URL` — Postgres URL. Plain `postgresql://…` is fine: Alembic rewrites it to the **psycopg v3** driver (`postgresql+psycopg://…`) because this package does not install `psycopg2`.

## Commands (local)

From `apps/migrations/`:

```bash
export DATABASE_URL=postgresql://zkast:zkast@localhost:5432/zkast
pip install -e .
alembic upgrade head
```

## Docker

Built from `Dockerfile`; Compose runs `alembic upgrade head` once against `postgres`.
