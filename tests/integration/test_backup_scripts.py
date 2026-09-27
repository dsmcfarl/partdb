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
            "PARTDB_DATABASE": urlparse(database_dsn).path.lstrip("/"),
            "PARTDB_BACKUP_TIMESTAMP": "2099-01-02T030405Z",
        }
    )
    return environment


def create_backup(root: Path, environment: dict[str, str], cwd: Path = REPO) -> Path:
    backup = subprocess.run(
        [str(REPO / "scripts/backup-local.sh"), str(root)],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    return Path(backup.stdout.strip().splitlines()[-1])


def rewrite_metadata(backup_dir: Path, replacements: dict[str, str]) -> None:
    metadata = backup_dir / "metadata.txt"
    content = metadata.read_text(encoding="utf-8")
    for old, new in replacements.items():
        assert old in content
        content = content.replace(old, new)
    metadata.write_text(content, encoding="utf-8")
    with (backup_dir / "SHA256SUMS").open("w", encoding="utf-8") as sums:
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
            stdout=sums,
            check=True,
        )


def verify_backup(
    backup_dir: Path | str, environment: dict[str, str], cwd: Path = REPO
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(REPO / "scripts/verify-backup.sh"), str(backup_dir)],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


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


def test_backup_ignores_partdb_dsn_pointing_elsewhere(
    database_dsn: str, conn: psycopg.Connection, tmp_path: Path
) -> None:
    service = InventoryService(conn)
    service.add_location("5A1")
    service.add_part("5A1", "washer")
    conn.commit()
    environment = script_environment(database_dsn)
    environment["PARTDB_DSN"] = "postgresql://partdb@127.0.0.1:1/elsewhere"

    backup_dir = create_backup(tmp_path / "compose only", environment)

    parts = (backup_dir / "parts.csv").read_text(encoding="utf-8")
    assert "5A1,washer" in parts


def test_relative_paths_resolve_from_the_caller_directory(
    database_dsn: str, conn: psycopg.Connection, tmp_path: Path
) -> None:
    InventoryService(conn).add_location("5A1")
    conn.commit()
    environment = script_environment(database_dsn)

    backup_dir = create_backup(Path("relative root"), environment, cwd=tmp_path)

    assert backup_dir.is_absolute()
    assert backup_dir.parent == tmp_path / "relative root"
    assert not list(tmp_path.rglob("*.incomplete"))
    assert not (REPO / "relative root").exists()
    relative = backup_dir.relative_to(tmp_path)
    verified = verify_backup(relative, environment, cwd=tmp_path)
    assert verified.returncode == 0, verified.stderr
    assert "locations=1" in verified.stdout


def test_validation_accepts_backup_from_older_pgvector(
    database_dsn: str, conn: psycopg.Connection, tmp_path: Path
) -> None:
    InventoryService(conn).add_location("5A1")
    conn.commit()
    environment = script_environment(database_dsn)
    backup_dir = create_backup(tmp_path / "old vector", environment)
    metadata = (backup_dir / "metadata.txt").read_text(encoding="utf-8")
    current = next(
        line.removeprefix("vector=")
        for line in metadata.splitlines()
        if line.startswith("vector=")
    )
    rewrite_metadata(backup_dir, {f"vector={current}": "vector=0.0.1"})

    result = verify_backup(backup_dir, environment)

    assert result.returncode == 0, result.stderr
    assert f"vector={current} (backup 0.0.1)" in result.stdout
    assert restore_database_count() == 0


@pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
def test_just_backup_preserves_destination_with_spaces(
    database_dsn: str, conn: psycopg.Connection, tmp_path: Path
) -> None:
    InventoryService(conn).add_location("5A1")
    conn.commit()
    root = tmp_path / "My Drive" / "PartDB"

    result = subprocess.run(
        ["just", "backup", str(root)],
        cwd=REPO,
        env=script_environment(database_dsn),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip().splitlines()[-1]).parent == root


def test_validation_rejects_metadata_mismatch_and_cleans_restore_database(
    database_dsn: str, conn: psycopg.Connection, tmp_path: Path
) -> None:
    service = InventoryService(conn)
    service.add_location("5A1")
    service.add_part("5A1", "washer")
    conn.commit()
    environment = script_environment(database_dsn)
    backup_dir = create_backup(tmp_path / "metadata", environment)
    rewrite_metadata(
        backup_dir,
        {
            "embeddings=0": "embeddings=999",
            "migration=003_require_part_fields": "migration=wrong",
        },
    )

    result = verify_backup(backup_dir, environment)

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
