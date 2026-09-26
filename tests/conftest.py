import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql


@pytest.fixture
def database_dsn() -> Iterator[str]:
    name = f"partdb_test_{uuid.uuid4().hex}"
    admin_dsn = os.getenv(
        "PARTDB_TEST_ADMIN_DSN",
        "postgresql://partdb@127.0.0.1:5435/postgres",
    )
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = f"postgresql://partdb@127.0.0.1:5435/{name}"
    try:
        yield dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
