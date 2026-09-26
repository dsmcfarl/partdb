import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest

from partdb.inventory import InventoryService

pytestmark = pytest.mark.integration
REPO = Path(__file__).resolve().parents[2]


def script_environment(database_dsn: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PARTDB_DSN": database_dsn,
            "PARTDB_DATABASE": urlparse(database_dsn).path.lstrip("/"),
            "PARTDB_BACKUP_TIMESTAMP": "2099-01-02T030405Z",
        }
    )
    return environment


def restore_database_count() -> int:
    with psycopg.connect("postgresql://partdb@127.0.0.1:5435/postgres") as connection:
        return connection.execute(
            "SELECT count(*) FROM pg_database WHERE datname LIKE 'partdb_restore_%'"
        ).fetchone()[0]


def test_backup_handles_spaces_and_restores_counts(
    database_dsn: str, conn: psycopg.Connection, tmp_path: Path
) -> None:
    service = InventoryService(conn)
    service.add_location("5A1")
    service.add_part("5A1", "washer")
    conn.commit()
    root = tmp_path / "archive with spaces"
    environment = script_environment(database_dsn)

    backup = subprocess.run(
        [str(REPO / "scripts/backup-local.sh"), str(root)],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    backup_dir = Path(backup.stdout.strip().splitlines()[-1])

    assert {path.name for path in backup_dir.iterdir()} == {
        "partdb.custom",
        "locations.csv",
        "parts.csv",
        "metadata.txt",
        "SHA256SUMS",
    }
    subprocess.run(
        ["shasum", "-a", "256", "-c", "SHA256SUMS"],
        cwd=backup_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    verified = subprocess.run(
        [str(REPO / "scripts/verify-backup.sh"), str(backup_dir)],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "locations=1" in verified.stdout
    assert "parts=1" in verified.stdout
    assert restore_database_count() == 0


def test_backup_rejects_mismatched_dsn_and_database(
    database_dsn: str, conn: psycopg.Connection, tmp_path: Path
) -> None:
    InventoryService(conn).add_location("5A1")
    conn.commit()
    environment = script_environment(database_dsn)
    environment["PARTDB_DATABASE"] = "partdb"

    result = subprocess.run(
        [str(REPO / "scripts/backup-local.sh"), str(tmp_path / "mixed")],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "PARTDB_DSN database must match PARTDB_DATABASE" in result.stderr


def test_validation_rejects_metadata_mismatch_and_cleans_restore_database(
    database_dsn: str, conn: psycopg.Connection, tmp_path: Path
) -> None:
    service = InventoryService(conn)
    service.add_location("5A1")
    service.add_part("5A1", "washer")
    conn.commit()
    environment = script_environment(database_dsn)
    backup = subprocess.run(
        [str(REPO / "scripts/backup-local.sh"), str(tmp_path / "metadata")],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    backup_dir = Path(backup.stdout.strip().splitlines()[-1])
    metadata = backup_dir / "metadata.txt"
    content = metadata.read_text(encoding="utf-8")
    metadata.write_text(
        content.replace("embeddings=0", "embeddings=999").replace(
            "migration=002_location_verification", "migration=wrong"
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "shasum",
            "-a",
            "256",
            "partdb.custom",
            "locations.csv",
            "parts.csv",
            "metadata.txt",
        ],
        cwd=backup_dir,
        text=True,
        stdout=(backup_dir / "SHA256SUMS").open("w", encoding="utf-8"),
        check=True,
    )

    result = subprocess.run(
        [str(REPO / "scripts/verify-backup.sh"), str(backup_dir)],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "embedding count mismatch" in result.stderr
    assert restore_database_count() == 0


def test_corrupt_dump_fails_without_leaving_restore_database(
    database_dsn: str, conn: psycopg.Connection, tmp_path: Path
) -> None:
    InventoryService(conn).add_location("5A1")
    conn.commit()
    environment = script_environment(database_dsn)
    root = tmp_path / "source"
    backup = subprocess.run(
        [str(REPO / "scripts/backup-local.sh"), str(root)],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    source = Path(backup.stdout.strip().splitlines()[-1])
    corrupt = tmp_path / "corrupt backup"
    shutil.copytree(source, corrupt)
    dump = corrupt / "partdb.custom"
    dump.write_bytes(dump.read_bytes()[:100])

    result = subprocess.run(
        [str(REPO / "scripts/verify-backup.sh"), str(corrupt)],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert restore_database_count() == 0
