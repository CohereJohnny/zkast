FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir "alembic>=1.14,<2" "psycopg[binary]>=3.2,<4"

COPY alembic.ini ./
COPY alembic ./alembic

CMD ["alembic", "upgrade", "head"]
