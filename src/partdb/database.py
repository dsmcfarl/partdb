import os

import psycopg

DEFAULT_DSN = "postgresql://partdb@127.0.0.1:5435/partdb"


def resolve_dsn(dsn: str | None = None) -> str:
    return dsn or os.getenv("PARTDB_DSN", DEFAULT_DSN)


def connect(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(resolve_dsn(dsn))
