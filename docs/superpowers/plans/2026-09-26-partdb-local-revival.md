# PartDB Local Revival Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Mac-hosted PostgreSQL/pgvector database authoritative, restore the real Euclid inventory into it, and deliver a tested offline-capable CLI with migration, audit, backup, and physical-verification workflows.

**Architecture:** Keep Click, psycopg, and direct SQL, but split the monolithic CLI into database, inventory, embedding, audit, and presentation modules. Run PostgreSQL 17 with pgvector in Docker Compose, evolve the legacy schema through ordered SQL migrations, and keep all real data and backup artifacts outside Git under the Archive.

**Tech Stack:** Python 3.11+, uv, Hatchling, Click, psycopg 3, PostgreSQL 17, pgvector 0.8.6, Docker Compose, pytest, Ruff, GitHub Actions, optional OpenAI Python client.

**Spec:** `docs/superpowers/specs/2026-09-26-partdb-local-revival-design.md`

## Global Constraints

- Keep the canonical checkout at `~/code/gh/dsmcfarl/partdb`; execute this plan in an isolated Git worktree created at implementation time.
- Use Python `>=3.11`; a clean `uv sync --locked --all-extras` must install the `partdb` console script.
- Use psycopg and direct SQL; do not introduce an ORM or application framework.
- Run `pgvector/pgvector:0.8.6-pg17` with PostgreSQL exposed only as `127.0.0.1:5435`.
- Store the authoritative local database in a persistent Docker volume.
- Never commit inventory data, database dumps, CSV exports, audit reports, or credentials.
- List, add, update, move, delete, full-text search, export, audit, and verification must work without OpenAI.
- Adding or changing a description without embedding generation must store `embedding = NULL`; never leave a stale vector.
- Only explicit `verify mark` and `verify clear` commands change `locations.verified_at`; ordinary inventory edits do not.
- Keep only the latest verification timestamp; do not add verification history.
- Write immutable migration and post-migration backup sets under `~/Documents/Archive/Interests/Workshop/PartDB/`.
- Do not perform bulk inventory corrections or build a web, mobile, or natural-language interface in this phase.

## Review Focus

- Case-insensitive duplicate endpoint names, unknown endpoints, reversed ranges, and mixed command forms must fail before any verification write; Task 5 pins each case.
- A legacy Euclid schema with existing data and no `schema_migrations` table must migrate without dropping or duplicating records; Task 2 pins this migration path.
- A missing OpenAI package or key must not break offline commands, and changed descriptions must not retain stale vectors; Task 4 pins both conditions.
- Cancelled destructive commands and unknown part/location identifiers must return nonzero without changing data; Task 3 pins rollback and no-op behavior.
- Backup paths containing spaces and a corrupt or incomplete dump must be handled safely: quoted paths succeed, corrupt dumps fail validation, and temporary restore databases are removed; Task 7 pins these conditions.

---

## Planned File Structure

| Path | Responsibility |
|---|---|
| `compose.yaml` | Localhost-only PostgreSQL 17/pgvector service and persistent volume |
| `pyproject.toml` | Build metadata, runtime/optional/dev dependencies, console entry point, tool configuration |
| `src/partdb/cli.py` | Click commands, validation, confirmation, and output |
| `src/partdb/main.py` | Backward-compatible import/`python -m` shim only |
| `src/partdb/database.py` | DSN resolution, connections, and transaction boundary helpers |
| `src/partdb/migrate.py` | Ordered SQL migration discovery and application |
| `src/partdb/migrations/001_initial.sql` | Idempotent baseline matching the Euclid schema |
| `src/partdb/migrations/002_location_verification.sql` | `verified_at` schema change |
| `src/partdb/models.py` | Typed records returned by inventory and audit services |
| `src/partdb/errors.py` | Domain exceptions translated by the CLI |
| `src/partdb/inventory.py` | CRUD, listing, full-text/vector search, CSV import/export, verification writes |
| `src/partdb/location_order.py` | Natural ordering and inclusive endpoint selection |
| `src/partdb/embeddings.py` | Optional provider protocol, OpenAI adapter, and refresh orchestration |
| `src/partdb/audit.py` | Read-only audit queries, normalization, and Markdown rendering |
| `scripts/backup-local.sh` | Produce a dated dump, CSV exports, metadata, and checksums |
| `scripts/verify-backup.sh` | List and restore a dump into a disposable database and compare counts |
| `tests/conftest.py` | Disposable PostgreSQL database fixture and CLI environment |
| `tests/unit/` | Pure ordering, audit-normalization, and embedding tests |
| `tests/integration/` | Migration, inventory, CLI, audit, and backup tests |
| `.github/workflows/ci.yml` | Locked install, Ruff, and pytest with pgvector service |
| `README.md` | Local setup, CLI, migration, verification, backup, and recovery runbook |
| `justfile` | Repeatable developer, database, test, backup, and restore commands |

### Task 1: Reproducible Package and Local Database Runtime

**Files:**
- Modify: `pyproject.toml`
- Create: `compose.yaml`
- Modify: `.gitignore`
- Create: `src/partdb/cli.py`
- Replace: `src/partdb/main.py`
- Create: `tests/unit/test_cli_smoke.py`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: no new internal interfaces.
- Produces: `partdb.cli:cli`, the `partdb` console script, and local DSN `postgresql://partdb@127.0.0.1:5435/partdb`.

- [ ] **Step 1: Write the failing console-entry test**

```python
# tests/unit/test_cli_smoke.py
from click.testing import CliRunner
from partdb.cli import cli


def test_help_lists_top_level_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Manage workshop parts and locations" in result.output


def test_version_is_installed() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "partdb, version 0.2.0" in result.output
```

- [ ] **Step 2: Run the test and verify the missing module failure**

Run: `uv run --with pytest pytest tests/unit/test_cli_smoke.py -v`

Expected: FAIL during collection because `partdb.cli` does not exist.

- [ ] **Step 3: Replace project metadata with an installable package**

Use this structure in `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "partdb"
version = "0.2.0"
description = "A tool for keeping track of where workshop parts are stored."
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "click>=8.1,<9",
    "psycopg[binary]>=3.2,<4",
]

[project.optional-dependencies]
embeddings = ["openai>=1.55,<4"]

[dependency-groups]
dev = [
    "pytest>=8.3,<9",
    "pytest-cov>=6,<8",
    "ruff>=0.8,<1",
]

[project.scripts]
partdb = "partdb.cli:cli"

[tool.hatch.build.targets.wheel]
packages = ["src/partdb"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--strict-markers"
markers = ["integration: requires PostgreSQL/pgvector"]

[tool.ruff]
target-version = "py311"
line-length = 88
```

Create `src/partdb/cli.py`:

```python
import click
from importlib.metadata import version


@click.group()
@click.version_option(version("partdb"))
def cli() -> None:
    """Manage workshop parts and locations."""
```

Replace `src/partdb/main.py` with the compatibility shim:

```python
from partdb.cli import cli


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Add the localhost-only Compose database**

Create `compose.yaml`:

```yaml
services:
  db:
    image: pgvector/pgvector:0.8.6-pg17
    environment:
      POSTGRES_DB: partdb
      POSTGRES_USER: partdb
      POSTGRES_HOST_AUTH_METHOD: trust
    ports:
      - "127.0.0.1:5435:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U partdb -d partdb"]
      interval: 2s
      timeout: 3s
      retries: 30
    volumes:
      - partdb-data:/var/lib/postgresql/data

volumes:
  partdb-data:
```

Add these patterns to `.gitignore`:

```gitignore
.env
.coverage
.pytest_cache/
.ruff_cache/
.venv/
*.custom
*.dump
/audit-*.md
```

- [ ] **Step 5: Regenerate the lock and verify installation**

Run:

```bash
uv lock
uv sync --locked --all-extras
uv run partdb --help
uv run partdb --version
uv run pytest tests/unit/test_cli_smoke.py -v
```

Expected: lock succeeds; console commands run; 2 tests pass.

- [ ] **Step 6: Verify Compose networking and persistence**

Run:

```bash
docker compose up -d --wait
docker compose port db 5432
docker compose exec -T db psql -U partdb -d partdb -Atqc 'select version();'
docker compose restart db
docker compose exec -T db psql -U partdb -d partdb -Atqc 'select 1;'
```

Expected: published endpoint is `127.0.0.1:5435`; both SQL commands succeed.

- [ ] **Step 7: Commit the runtime foundation**

```bash
git add pyproject.toml uv.lock compose.yaml .gitignore src/partdb/cli.py src/partdb/main.py tests/unit/test_cli_smoke.py
git commit -m "build: add reproducible local runtime"
```

### Task 2: Database Connections and Idempotent Schema Migrations

**Files:**
- Create: `src/partdb/database.py`
- Create: `src/partdb/migrate.py`
- Create: `src/partdb/migrations/__init__.py`
- Create: `src/partdb/migrations/001_initial.sql`
- Create: `src/partdb/migrations/002_location_verification.sql`
- Create: `tests/conftest.py`
- Create: `tests/integration/test_migrations.py`
- Modify: `src/partdb/cli.py`

**Interfaces:**
- Consumes: `PARTDB_DSN` or default local DSN.
- Produces: `database.resolve_dsn() -> str`, `database.connect(dsn: str | None = None) -> psycopg.Connection`, `migrate.apply_migrations(conn) -> list[str]`, and `partdb db migrate`.

- [ ] **Step 1: Add disposable-database fixtures**

Create `tests/conftest.py` with a session fixture that connects to `PARTDB_TEST_ADMIN_DSN` (default `postgresql://partdb@127.0.0.1:5435/postgres`), creates a uniquely named database using `psycopg.sql.Identifier`, yields its DSN, and drops that quoted database with `WITH (FORCE)` in `finally`. Add a function fixture that connects to that DSN and rolls back or truncates between tests.

Core fixture shape:

```python
@pytest.fixture(scope="session")
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
```

- [ ] **Step 2: Write failing fresh, legacy, and idempotency migration tests**

```python
def test_migrate_fresh_database(database_dsn: str) -> None:
    with psycopg.connect(database_dsn) as conn:
        assert apply_migrations(conn) == ["001_initial", "002_location_verification"]
        columns = column_names(conn, "locations")
        assert columns == {"name", "verified_at"}
        assert extension_names(conn) >= {"plpgsql", "vector"}


def test_migrate_legacy_database_preserves_rows(database_dsn: str) -> None:
    with psycopg.connect(database_dsn) as conn:
        conn.execute("CREATE EXTENSION vector")
        conn.execute("CREATE TABLE locations (name varchar(255) PRIMARY KEY)")
        conn.execute("""CREATE TABLE parts (
            id serial PRIMARY KEY,
            location varchar(255) REFERENCES locations(name),
            description text,
            embedding vector(1536))""")
        conn.execute("INSERT INTO locations(name) VALUES ('5A1')")
        conn.execute(
            "INSERT INTO parts(location, description) VALUES ('5A1', 'M3 bolts')"
        )
        apply_migrations(conn)
        assert conn.execute("SELECT count(*) FROM locations").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM parts").fetchone()[0] == 1
        assert conn.execute(
            "SELECT verified_at IS NULL FROM locations WHERE name='5A1'"
        ).fetchone()[0]


def test_second_migration_run_is_a_noop(database_dsn: str) -> None:
    with psycopg.connect(database_dsn) as conn:
        apply_migrations(conn)
        assert apply_migrations(conn) == []
```

- [ ] **Step 3: Run migration tests and verify failure**

Run: `uv run pytest tests/integration/test_migrations.py -v -m integration`

Expected: FAIL because `database.py`, migration SQL, and `apply_migrations` do not exist.

- [ ] **Step 4: Implement connection resolution**

Create `src/partdb/database.py`:

```python
import os
import psycopg

DEFAULT_DSN = "postgresql://partdb@127.0.0.1:5435/partdb"


def resolve_dsn(dsn: str | None = None) -> str:
    return dsn or os.getenv("PARTDB_DSN", DEFAULT_DSN)


def connect(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(resolve_dsn(dsn))
```

- [ ] **Step 5: Add baseline and verification SQL**

`001_initial.sql` must contain:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS locations (
    name VARCHAR(255) PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS parts (
    id SERIAL PRIMARY KEY,
    location VARCHAR(255) NOT NULL REFERENCES locations(name),
    description TEXT NOT NULL,
    embedding vector(1536)
);
```

`002_location_verification.sql` must contain:

```sql
ALTER TABLE locations
    ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ NULL;
```

- [ ] **Step 6: Implement ordered migration application**

`apply_migrations` must create `schema_migrations(version text primary key, applied_at timestamptz not null default now())`, discover `*.sql` through `importlib.resources.files("partdb.migrations")`, sort by filename, and execute each unrecorded file plus its insert into `schema_migrations` in one `conn.transaction()`.

Use these exact semantics:

```python
def apply_migrations(conn: psycopg.Connection) -> list[str]:
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    applied = {
        row[0] for row in conn.execute("SELECT version FROM schema_migrations")
    }
    completed: list[str] = []
    root = resources.files("partdb.migrations")
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.suffix != ".sql":
            continue
        version = path.stem
        if version in applied:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations(version) VALUES (%s)", (version,)
            )
        completed.append(version)
    return completed
```

- [ ] **Step 7: Add and test `partdb db migrate`**

Add a `db` Click group and `migrate` command that opens `database.connect()`, calls `apply_migrations`, and prints either the applied versions or `database already current`. Translate `psycopg.Error` into `click.ClickException`.

Run:

```bash
uv run pytest tests/integration/test_migrations.py -v -m integration
PARTDB_DSN=postgresql://partdb@127.0.0.1:5435/partdb uv run partdb db migrate
```

Expected: all migration tests pass and the local database reports both versions.

- [ ] **Step 8: Commit migration infrastructure**

```bash
git add src/partdb/database.py src/partdb/migrate.py src/partdb/migrations tests/conftest.py tests/integration/test_migrations.py src/partdb/cli.py
git commit -m "feat: add versioned database migrations"
```

### Task 3: Offline Inventory CRUD and Backward-Compatible Commands

**Files:**
- Create: `src/partdb/models.py`
- Create: `src/partdb/errors.py`
- Create: `src/partdb/inventory.py`
- Modify: `src/partdb/cli.py`
- Create: `tests/integration/test_inventory.py`
- Create: `tests/integration/test_cli_inventory.py`

**Interfaces:**
- Consumes: migrated `locations` and `parts` tables and `database.connect()`.
- Produces: `Part`, `Location`, `InventoryService`, domain exceptions, and existing `add`, `list`, `update`, `move`, and `delete` CLI forms.

- [ ] **Step 1: Define tests for CRUD, stale-vector removal, and domain failures**

Tests must establish this behavior:

```python
def test_update_description_clears_stale_embedding(conn) -> None:
    service = InventoryService(conn)
    service.add_location("5A1")
    part = service.add_part("5A1", "M3 bolt")
    conn.execute(
        "UPDATE parts SET embedding = array_fill(0.1::real, ARRAY[1536])::vector WHERE id=%s",
        (part.id,),
    )
    service.update_part(part.id, "M3 socket head bolt")
    assert conn.execute(
        "SELECT description, embedding IS NULL FROM parts WHERE id=%s", (part.id,)
    ).fetchone() == ("M3 socket head bolt", True)


def test_move_to_unknown_location_rolls_back(conn) -> None:
    service = InventoryService(conn)
    service.add_location("5A1")
    part = service.add_part("5A1", "washer")
    with pytest.raises(LocationNotFound, match="5B1"):
        service.move_part(part.id, "5B1")
    assert service.get_part(part.id).location == "5A1"


def test_unknown_part_delete_does_not_change_rows(conn) -> None:
    service = InventoryService(conn)
    before = service.part_count()
    with pytest.raises(PartNotFound, match="999"):
        service.delete_part(999)
    assert service.part_count() == before
```

CLI tests must cover existing syntax, integer validation, an aborted delete, `delete --id 999 --yes`, and deleting a populated location without cascading its parts.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
uv run pytest tests/integration/test_inventory.py tests/integration/test_cli_inventory.py -v -m integration
```

Expected: FAIL because service types and commands do not exist.

- [ ] **Step 3: Add typed records and domain errors**

Use frozen dataclasses:

```python
@dataclass(frozen=True)
class Location:
    name: str
    verified_at: datetime | None


@dataclass(frozen=True)
class Part:
    id: int
    location: str
    description: str
    has_embedding: bool
```

Define `PartDBError`, `LocationNotFound`, `PartNotFound`, `LocationNotEmpty`, and `DuplicateLocation` in `errors.py`.

- [ ] **Step 4: Implement `InventoryService` CRUD**

Implement `InventoryService` with a constructor accepting `psycopg.Connection` and these exact public signatures: `list_locations() -> list[Location]`, `list_parts(location: str | None = None) -> list[Part]`, `get_part(part_id: int) -> Part`, `part_count() -> int`, `add_location(name: str) -> Location`, `add_part(location: str, description: str) -> Part`, `update_part(part_id: int, description: str) -> Part`, `move_part(part_id: int, location: str) -> Part`, `delete_part(part_id: int) -> None`, and `delete_location(name: str) -> None`.

Validate nonblank names/descriptions. Use `RETURNING` to distinguish success from unknown IDs. `update_part` sets `embedding = NULL`. `delete_location` catches foreign-key violations and raises `LocationNotEmpty`. Service methods do not commit; the connection context used by the CLI owns commit/rollback.

- [ ] **Step 5: Recreate existing CLI behavior through the service**

Implement and retain these forms:

```text
partdb add LOCATION [DESCRIPTION]
partdb list [LOCATION]
partdb list --locations
partdb update PART_ID DESCRIPTION
partdb move PART_ID LOCATION
partdb delete --id PART_ID [--yes]
partdb delete --location LOCATION [--yes]
```

Use `type=int` for IDs. Reject both/neither delete targets. Prompt before deletion unless `--yes` is present. Wrap each command with a connection context and translate `PartDBError`/`psycopg.Error` into `click.ClickException`.

- [ ] **Step 6: Run tests, then run a local smoke sequence**

Run:

```bash
uv run pytest tests/integration/test_inventory.py tests/integration/test_cli_inventory.py -v -m integration
PARTDB_DSN=postgresql://partdb@127.0.0.1:5435/partdb uv run partdb add TEST1
PARTDB_DSN=postgresql://partdb@127.0.0.1:5435/partdb uv run partdb add TEST1 "temporary smoke part"
PARTDB_DSN=postgresql://partdb@127.0.0.1:5435/partdb uv run partdb list TEST1
```

Expected: tests pass and the smoke part is listed. Remove it and `TEST1` with explicit `--yes` commands before continuing.

- [ ] **Step 7: Commit offline CRUD**

```bash
git add src/partdb/models.py src/partdb/errors.py src/partdb/inventory.py src/partdb/cli.py tests/integration/test_inventory.py tests/integration/test_cli_inventory.py
git commit -m "feat: restore offline inventory commands"
```

### Task 4: Full-Text Search, CSV Round Trip, and Optional Embeddings

**Files:**
- Create: `src/partdb/embeddings.py`
- Modify: `src/partdb/inventory.py`
- Modify: `src/partdb/cli.py`
- Create: `tests/unit/test_embeddings.py`
- Create: `tests/integration/test_search_and_csv.py`

**Interfaces:**
- Consumes: `InventoryService`, migrated vector column, optional `openai` package and `OPENAI_API_KEY`.
- Produces: `EmbeddingProvider.embed(text: str) -> list[float]`, `OpenAIEmbeddingProvider`, `InventoryService.search_full_text`, `search_semantic`, `refresh_embeddings`, `dump_csv`, and `load_csv`.

- [ ] **Step 1: Write tests for an absent OpenAI dependency and fake-provider refresh**

```python
class FakeProvider:
    def embed(self, text: str) -> list[float]:
        return [float(len(text))] * 1536


def test_offline_commands_do_not_import_openai(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    from partdb.embeddings import EmbeddingProvider
    assert EmbeddingProvider is not None


def test_refresh_only_missing_embeddings(conn) -> None:
    service = seeded_service(conn)
    changed = service.refresh_embeddings(FakeProvider(), refresh_all=False)
    assert changed == 2
    assert conn.execute(
        "SELECT count(*) FROM parts WHERE embedding IS NULL"
    ).fetchone()[0] == 0
```

Integration tests must also cover web-style full-text queries, semantic exclusion of NULL embeddings, CSV headers and row round trip, blank/malformed CSV rejection with rollback, and `search` without a key returning a clear nonzero error rather than an import traceback.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/unit/test_embeddings.py tests/integration/test_search_and_csv.py -v
```

Expected: FAIL because embedding and search interfaces do not exist.

- [ ] **Step 3: Implement lazy optional embedding support**

Define a protocol and lazy adapter:

```python
class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class OpenAIEmbeddingProvider:
    def __init__(self) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            raise EmbeddingUnavailable("OPENAI_API_KEY is not configured")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise EmbeddingUnavailable(
                "install the 'embeddings' extra to use semantic search"
            ) from exc
        self._client = OpenAI()

    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings.create(
            input=text.replace("\n", " ")[:8191],
            model="text-embedding-3-small",
        )
        return response.data[0].embedding
```

Define `EmbeddingUnavailable` under `errors.py`. No module imported by offline commands may import `openai` at module load time.

- [ ] **Step 4: Implement search and refresh queries**

- Full text: `to_tsvector('simple', description) @@ websearch_to_tsquery('simple', %s)`.
- Semantic: `WHERE embedding IS NOT NULL ORDER BY embedding <=> %s::vector LIMIT %s`.
- Refresh: select missing rows unless `refresh_all=True`, call the provider, validate exactly 1536 values, and update each vector in the command transaction.

Keep the existing nearest-empty-location fields in search results and cover both directions in integration tests.

- [ ] **Step 5: Implement transactional CSV dump/load**

Preserve the public file names and headers:

```text
locations.csv: name
parts.csv: location,description
```

Write UTF-8 with `newline=""`. Validate both complete files and every row before inserting. Reject duplicate locations, unknown part locations, blank cells, and extra/missing columns; any error must leave the database unchanged.

- [ ] **Step 6: Wire CLI commands**

```text
partdb search [--full-text] DESCRIPTION
partdb dumpdb [--path DIRECTORY]
partdb loaddb [--path DIRECTORY]
partdb embeddings refresh [--all]
```

Default `search` remains semantic for backward compatibility; `--full-text` is always offline. `embeddings refresh` instantiates `OpenAIEmbeddingProvider` only after command dispatch.

- [ ] **Step 7: Run focused and complete tests**

Run:

```bash
uv run pytest tests/unit/test_embeddings.py tests/integration/test_search_and_csv.py -v
uv run pytest -v
```

Expected: all tests pass without setting `OPENAI_API_KEY`.

- [ ] **Step 8: Commit search, CSV, and optional embeddings**

```bash
git add src/partdb/embeddings.py src/partdb/errors.py src/partdb/inventory.py src/partdb/cli.py tests/unit/test_embeddings.py tests/integration/test_search_and_csv.py
git commit -m "feat: add offline search and optional embeddings"
```

### Task 5: Natural Location Ranges and Physical Verification

**Files:**
- Create: `src/partdb/location_order.py`
- Modify: `src/partdb/models.py`
- Modify: `src/partdb/inventory.py`
- Modify: `src/partdb/cli.py`
- Create: `tests/unit/test_location_order.py`
- Create: `tests/integration/test_verification.py`
- Create: `tests/integration/test_cli_verification.py`

**Interfaces:**
- Consumes: `locations.verified_at`, `InventoryService`, Click confirmation.
- Produces: `natural_location_key(name)`, `inclusive_location_range(names, start, end)`, `InventoryLocation`, verification service methods, and `inventory`/`verify` commands.

- [ ] **Step 1: Write natural-order and invalid-range unit tests**

Pin these sequences and failures:

```python
def test_natural_order_matches_physical_labels() -> None:
    names = ["5A10", "PO2", "5A2", "1B1", "PO1", "5A1"]
    assert sorted(names, key=natural_location_key) == [
        "1B1", "5A1", "5A2", "5A10", "PO1", "PO2"
    ]


def test_range_is_inclusive_and_case_insensitive() -> None:
    names = ["5A1", "5A2", "5A3", "5A8"]
    assert inclusive_location_range(names, "5a1", "5a3") == [
        "5A1", "5A2", "5A3"
    ]

@pytest.mark.parametrize(
    "names,start,end,message",
    [
        (["5A1"], "5A1", "5A9", "unknown range endpoint"),
        (["5A1", "5A2"], "5A2", "5A1", "range is reversed"),
        (["5A1", "5a1"], "5A1", "5A1", "ambiguous range endpoint"),
    ],
)
def test_invalid_ranges_fail(names, start, end, message) -> None:
    with pytest.raises(InvalidLocationRange, match=message):
        inclusive_location_range(names, start, end)
```

- [ ] **Step 2: Write verification integration and CLI tests**

Cover:

- Inventory range includes empty locations and groups parts by location.
- `mark_verified([names], verified_at=fixed_time)` updates exactly those names.
- `clear_verification([names])` sets NULL.
- Ordinary add/update/move/delete operations do not alter `verified_at`.
- Positional names and `--from/--through` cannot be combined.
- Supplying only one range endpoint fails.
- A declined range confirmation writes nothing.
- `--yes` marks the full displayed range.
- Unknown, reversed, and ambiguous ranges write nothing.
- `verify status --unverified` reports totals and naturally ordered names.

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
uv run pytest tests/unit/test_location_order.py tests/integration/test_verification.py tests/integration/test_cli_verification.py -v
```

Expected: FAIL because range and verification APIs do not exist.

- [ ] **Step 4: Implement natural ordering and endpoint selection**

Tokenize alternating digit and nondigit runs. Numeric runs sort as integers; text runs sort uppercase. Include the uppercase full name as a final deterministic tiebreaker:

```python
def natural_location_key(name: str) -> tuple[tuple[int, int | str], ...]:
    tokens = re.findall(r"\d+|\D+", name.strip())
    return tuple(
        (0, int(token)) if token.isdigit() else (1, token.upper())
        for token in tokens
    ) + ((2, name.upper()),)
```

`inclusive_location_range` builds a casefolded endpoint index, rejects duplicate casefolded names as ambiguous, validates both endpoints, sorts all names naturally, rejects reversed indexes, and returns the inclusive slice.

- [ ] **Step 5: Implement inventory grouping and verification methods**

Add `InventoryLocation(name, verified_at, parts)` and these exact `InventoryService` signatures: `inventory_range(start: str, end: str) -> list[InventoryLocation]`, `mark_verified(names: Sequence[str], verified_at: datetime | None = None) -> int`, `clear_verification(names: Sequence[str]) -> int`, and `verification_status(unverified_only: bool = False) -> list[Location]`.

Default `verified_at` to timezone-aware UTC `datetime.now(timezone.utc)`. Resolve and validate every name before executing a single update.

- [ ] **Step 6: Add inventory and verification commands**

Implement:

```text
partdb inventory --from START --through END
partdb verify mark NAME [NAME …] [--from START --through END] [--yes]
partdb verify clear NAME [NAME …] [--yes]
partdb verify status [--unverified]
```

Display all locations and parts before the confirmation prompt for range marking. Format timestamps as ISO 8601 UTC and unverified locations as `unverified`.

- [ ] **Step 7: Run tests and manually inspect the example range**

Run:

```bash
uv run pytest tests/unit/test_location_order.py tests/integration/test_verification.py tests/integration/test_cli_verification.py -v
```

Expected: tests pass; the CLI integration output is naturally ordered and includes empty locations. The real `5A1` through `5A8` smoke check occurs after restoration in Task 9.

- [ ] **Step 8: Commit verification workflow**

```bash
git add src/partdb/location_order.py src/partdb/models.py src/partdb/inventory.py src/partdb/cli.py tests/unit/test_location_order.py tests/integration/test_verification.py tests/integration/test_cli_verification.py
git commit -m "feat: add physical location verification"
```

### Task 6: Read-Only Data Quality Audit

**Files:**
- Create: `src/partdb/audit.py`
- Modify: `src/partdb/cli.py`
- Create: `tests/unit/test_audit.py`
- Create: `tests/integration/test_audit.py`

**Interfaces:**
- Consumes: migrated inventory database.
- Produces: `AuditFinding`, `AuditReport`, `normalize_description`, `run_audit(conn)`, `render_markdown(report)`, and `partdb audit`.

- [ ] **Step 1: Write normalization and rendering tests**

```python
def test_normalize_description_collapses_case_and_whitespace() -> None:
    assert normalize_description("  M3   Socket\nHead Bolt ") == "m3 socket head bolt"


def test_render_markdown_orders_severity_and_code() -> None:
    report = AuditReport(
        summary={"locations": 2, "parts": 2, "verified": 0, "unverified": 2},
        findings=(
            AuditFinding("warning", "normalized_duplicate", "two descriptions", (1, 2)),
            AuditFinding("error", "blank_description", "part 2 is blank", (2,)),
        ),
    )
    text = render_markdown(report)
    assert text.index("blank_description") < text.index("normalized_duplicate")
```

- [ ] **Step 2: Write an integration fixture containing every finding class**

Seed locations `5A1`, `5a1`, `5A2`, and `BAD LOCATION`; seed blank, exact-duplicate, normalized-duplicate, and missing-embedding parts. In the disposable test database, drop `parts_location_fkey`, insert one orphan, run and assert the audit, delete the orphan, and recreate the foreign key before fixture cleanup. Assert codes and affected IDs/names, plus verified/unverified totals.

Also test that `partdb audit --output report.md` exits 0 with findings and that a bad DSN exits nonzero without creating the output file.

- [ ] **Step 3: Run audit tests and verify failure**

Run: `uv run pytest tests/unit/test_audit.py tests/integration/test_audit.py -v`

Expected: FAIL because audit types and command do not exist.

- [ ] **Step 4: Implement immutable audit models and normalization**

```python
@dataclass(frozen=True)
class AuditFinding:
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    record_ids: tuple[int | str, ...] = ()


@dataclass(frozen=True)
class AuditReport:
    summary: Mapping[str, int]
    findings: tuple[AuditFinding, ...]


def normalize_description(value: str) -> str:
    return " ".join(value.casefold().split())
```

- [ ] **Step 5: Implement read-only checks**

`run_audit` must issue only `SELECT` statements and report:

- `empty_location`
- `blank_description`
- `exact_duplicate`
- `normalized_duplicate`
- `noncanonical_location_name` for names outside `^(?:[0-9]+[A-Z]+[0-9]+|[A-Z]+[0-9]+)$`
- `case_colliding_location`
- `missing_embedding`
- `orphan_part`

Include location, part, verified, and unverified counts. Render deterministic Markdown with summary first and findings grouped `error`, `warning`, `info`, then code/message.

- [ ] **Step 6: Add `partdb audit` output behavior**

`partdb audit` writes Markdown to stdout. `--output PATH` writes atomically using a sibling temporary file followed by `os.replace`; create parent directories only when explicitly supplied. Findings do not change exit status. Database or write failures return nonzero.

- [ ] **Step 7: Run tests and verify audit performs no writes**

Run:

```bash
uv run pytest tests/unit/test_audit.py tests/integration/test_audit.py -v
uv run pytest -v
```

Expected: all tests pass. The integration test compares table snapshots before and after `run_audit` and finds no changes.

- [ ] **Step 8: Commit audit support**

```bash
git add src/partdb/audit.py src/partdb/cli.py tests/unit/test_audit.py tests/integration/test_audit.py
git commit -m "feat: add read-only inventory audit"
```

### Task 7: Reproducible Backup and Restore Validation

**Files:**
- Create: `scripts/backup-local.sh`
- Create: `scripts/verify-backup.sh`
- Create: `tests/integration/test_backup_scripts.py`
- Modify: `.gitignore`
- Modify: `justfile`

**Interfaces:**
- Consumes: running Compose database, installed CLI, destination path.
- Produces: dated backup directory containing `partdb.custom`, `locations.csv`, `parts.csv`, `metadata.txt`, and `SHA256SUMS`; restore validation with a disposable database.

- [ ] **Step 1: Write end-to-end script tests**

The test invokes scripts through `subprocess.run` with `PARTDB_BACKUP_TIMESTAMP=2099-01-02T030405Z` and a `tmp_path / "archive with spaces"`. Assert exact artifact names, `shasum -a 256 -c SHA256SUMS` success, and validation output containing matching location/part counts.

Create a truncated copy with `dump.write_bytes(dump.read_bytes()[:100])`; assert `verify-backup.sh` exits nonzero and leaves no database matching `partdb_restore_*` in `pg_database`.

- [ ] **Step 2: Run the backup test and verify failure**

Run: `uv run pytest tests/integration/test_backup_scripts.py -v -m integration`

Expected: FAIL because the scripts do not exist.

- [ ] **Step 3: Implement `backup-local.sh` defensively**

Start with:

```bash
#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
root=${1:-"$HOME/Documents/Archive/Interests/Workshop/PartDB"}
stamp=${PARTDB_BACKUP_TIMESTAMP:-$(date -u +%Y-%m-%dT%H%M%SZ)}
dest="$root/$stamp-local"
tmp="$dest.incomplete"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp"
cd "$repo"
docker compose exec -T db pg_dump -U partdb -d partdb \
  --format=custom --no-owner --no-acl > "$tmp/partdb.custom"
PARTDB_DSN=${PARTDB_DSN:-postgresql://partdb@127.0.0.1:5435/partdb} \
  uv run partdb dumpdb --path "$tmp"
docker compose exec -T db psql -U partdb -d partdb -At <<'SQL' > "$tmp/metadata.txt"
SELECT 'postgres=' || version();
SELECT 'vector=' || extversion FROM pg_extension WHERE extname='vector';
SELECT 'locations=' || count(*) FROM locations;
SELECT 'parts=' || count(*) FROM parts;
SELECT 'embeddings=' || count(*) FROM parts WHERE embedding IS NOT NULL;
SELECT 'migration=' || coalesce(max(version), 'none') FROM schema_migrations;
SQL
(cd "$tmp" && shasum -a 256 partdb.custom locations.csv parts.csv metadata.txt > SHA256SUMS)
mv "$tmp" "$dest"
trap - EXIT
printf '%s\n' "$dest"
```

Before creating `$tmp`, fail if either `$dest` or `$tmp` already exists. Quote every expansion. Make the script executable.

- [ ] **Step 4: Implement restore validation with guaranteed cleanup**

`verify-backup.sh BACKUP_DIR` must:

1. Validate required files and `shasum -a 256 -c SHA256SUMS`.
2. Run `pg_restore --list` against the dump.
3. Create a random `partdb_restore_<hex>` database.
4. Restore with `--no-owner --no-acl --exit-on-error`.
5. Query location, part, embedding, vector extension, and migration counts.
6. Compare location/part counts to `metadata.txt`.
7. Drop the temporary database in an EXIT trap using `dropdb --force`.
8. Exit nonzero on corruption, restore errors, or mismatched counts.

Pass the dump through stdin to the container so backup paths with spaces remain safe:

```bash
docker compose exec -T db pg_restore --list < "$dir/partdb.custom" >/dev/null
docker compose exec -T db createdb -U partdb "$restore_db"
docker compose exec -T db pg_restore -U partdb -d "$restore_db" \
  --no-owner --no-acl --exit-on-error < "$dir/partdb.custom"
```

- [ ] **Step 5: Add Just recipes and ignore incomplete artifacts**

Provide `backup *args` and `verify-backup path` recipes that call the scripts. Ignore `*.incomplete` and local `backups/` paths.

- [ ] **Step 6: Run corruption, spaces, and cleanup tests**

Run:

```bash
uv run pytest tests/integration/test_backup_scripts.py -v -m integration
just backup /tmp/partdb-backup-smoke
just verify-backup "$(find /tmp/partdb-backup-smoke -mindepth 1 -maxdepth 1 -type d | head -1)"
```

Expected: tests pass; valid backup verifies; corrupt backup test exits nonzero and cleanup assertion passes.

- [ ] **Step 7: Commit backup tooling**

```bash
git add scripts/backup-local.sh scripts/verify-backup.sh tests/integration/test_backup_scripts.py .gitignore justfile
git commit -m "feat: add verified local database backups"
```

### Task 8: CI, Developer Commands, and Operating Documentation

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `justfile`
- Rewrite: `README.md`
- Create: `tests/unit/test_documented_commands.py`

**Interfaces:**
- Consumes: all application and script commands from Tasks 1–7.
- Produces: one-command local setup/test workflows and CI verification.

- [ ] **Step 1: Write a documentation-command consistency test**

Read `README.md` and `justfile`; assert the documented recipes `install`, `up`, `down`, `migrate`, `test`, `lint`, `backup`, and `verify-backup` all exist. Assert README mentions `PARTDB_DSN`, optional `OPENAI_API_KEY`, the Archive path, restore validation, and verification commands.

- [ ] **Step 2: Run the consistency test and verify failure**

Run: `uv run pytest tests/unit/test_documented_commands.py -v`

Expected: FAIL because the full recipes and runbook are absent.

- [ ] **Step 3: Replace the Just recipes**

Define:

```make
install:
    uv sync --locked --all-extras
up:
    docker compose up -d --wait
    uv run partdb db migrate
down:
    docker compose down
test:
    docker compose up -d --wait
    uv run pytest -v
lint:
    uv run ruff check .
    uv run ruff format --check .
format:
    uv run ruff check --fix .
    uv run ruff format .
backup *args:
    scripts/backup-local.sh {{args}}
verify-backup path:
    scripts/verify-backup.sh "{{path}}"
```

Use valid Just syntax and tabs/spaces accepted by the installed Just version.

- [ ] **Step 4: Rewrite README as the operating runbook**

Document in order:

1. Purpose and data model.
2. `uv sync --locked --all-extras` and `docker compose up -d --wait`.
3. `PARTDB_DSN` default and localhost-only database.
4. Migration command.
5. Existing CRUD/list/search/CSV commands.
6. Offline behavior and optional `OPENAI_API_KEY`/embedding refresh.
7. `inventory` and `verify` workflows with `5A1`–`5A8` examples.
8. Audit output privacy.
9. Archive backup creation and validation.
10. Recovery from a custom dump.
11. Test/lint commands and CI.

Do not include real inventory descriptions, counts that will become stale, credentials, or dump paths from a particular run.

- [ ] **Step 5: Add GitHub Actions**

Create `.github/workflows/ci.yml` triggered by pushes and pull requests. Use Python 3.11 and `astral-sh/setup-uv`. Add a `pgvector/pgvector:0.8.6-pg17` service with `POSTGRES_USER=partdb`, `POSTGRES_DB=partdb`, `POSTGRES_HOST_AUTH_METHOD=trust`, port `5435:5432`, and `pg_isready` health options.

Set:

```yaml
env:
  PARTDB_TEST_ADMIN_DSN: postgresql://partdb@127.0.0.1:5435/postgres
```

Steps must run:

```text
uv sync --locked --all-extras
uv run ruff check .
uv run ruff format --check .
uv run pytest -v
```

- [ ] **Step 6: Run the same gate locally**

Run:

```bash
uv sync --locked --all-extras
uv run ruff check .
uv run ruff format --check .
uv run pytest -v
```

Expected: every command exits 0.

- [ ] **Step 7: Commit CI and documentation**

```bash
git add .github/workflows/ci.yml justfile README.md tests/unit/test_documented_commands.py
git commit -m "docs: add local operations and CI runbook"
```

### Task 9: Back Up Euclid, Restore Real Data Locally, and Cut Over

**Files:**
- Create outside Git: `~/Documents/Archive/Interests/Workshop/PartDB/<timestamp>-euclid-pre-cutover/`
- Create outside Git: `~/Documents/Archive/Interests/Workshop/PartDB/<timestamp>-local-post-migration/`
- Create outside Git: `~/Documents/Archive/Interests/Workshop/PartDB/<timestamp>-inventory-audit.md`
- Modify in Git only if acceptance exposes a defect: the owning source/test/documentation files from Tasks 1–8

**Interfaces:**
- Consumes: Euclid `service=partdb`, SSH access, local Compose database, migration and backup commands.
- Produces: authoritative local database, verified pre/post backup sets, private audit report, and acceptance evidence.

- [ ] **Step 1: Load the filing instructions before creating Archive artifacts**

Read the `fileit` skill and confirm `~/Documents/Archive/Interests/Workshop/PartDB/` matches the Archive taxonomy. If the skill requires a different final directory, use that directory consistently for all remaining commands and record it in the acceptance notes; do not place artifacts in Git.

- [ ] **Step 2: Capture immutable Euclid source metadata**

Create a local staging directory with mode 700. Through SSH with `RemoteCommand=none`, record only non-secret metadata:

```text
source_host=euclid
postgres_version=<query result>
vector_version=<query result>
locations=<count>
parts=<count>
embeddings=<count>
```

Expected source counts from discovery are 195 locations, 201 parts, and 201 embeddings. If live counts differ, stop and investigate rather than forcing the old expected values.

- [ ] **Step 3: Create fresh Euclid dump and CSV exports**

On Euclid, use its PostgreSQL 17 client:

```bash
pg_dump "service=partdb" --format=custom --no-owner --no-acl \
  --file /tmp/partdb-euclid-pre-cutover.custom
psql "service=partdb" --csv -c \
  "SELECT name FROM locations ORDER BY name" \
  > /tmp/locations.csv
psql "service=partdb" --csv -c \
  "SELECT location, description FROM parts ORDER BY location, description" \
  > /tmp/parts.csv
(cd /tmp && sha256sum partdb-euclid-pre-cutover.custom locations.csv parts.csv \
  > SHA256SUMS)
```

Copy the dump, two CSV files, and source checksum file to the dated pre-cutover Archive directory. Verify the three copied files against the source checksums, add the metadata file from Step 2, then replace the source checksum file with a local `SHA256SUMS` covering the dump, both CSV files, and metadata. Verify that final manifest locally, then delete only the temporary `/tmp` copies from Euclid.

- [ ] **Step 4: Validate the Euclid backup before touching local authority**

Run `pg_restore --list` using the local PostgreSQL 17 container against the copied custom dump. Restore it into a disposable database, query source counts, and drop the disposable database in a cleanup trap. Do not proceed unless location, part, and embedding counts match Step 2.

- [ ] **Step 5: Reset only the local Compose volume and restore real data**

Confirm the current directory is the implementation worktree and the Compose project is PartDB. Then:

```bash
docker compose down -v
docker compose up -d --wait
docker compose exec -T db dropdb -U partdb --if-exists --force partdb
docker compose exec -T db createdb -U partdb partdb
docker compose exec -T db pg_restore -U partdb -d partdb \
  --no-owner --no-acl --exit-on-error \
  < "$PRE_CUTOVER_DIR/partdb-euclid-pre-cutover.custom"
PARTDB_DSN=postgresql://partdb@127.0.0.1:5435/partdb uv run partdb db migrate
```

The `down -v` command is permitted only here, before the Mac database becomes authoritative. It must not appear in ordinary runbook commands.

- [ ] **Step 6: Compare restored data and run read-only smoke tests**

Query and record:

- Location count.
- Part count.
- Populated embedding count.
- Minimum and maximum part IDs.
- Vector extension version.
- Applied migration versions.

Run:

```bash
uv run partdb list --locations
uv run partdb list
uv run partdb search --full-text resistor
uv run partdb inventory --from 5A1 --through 5A8
uv run partdb verify status --unverified
```

Capture counts, not full private output, in acceptance notes. Do not run modifying inventory commands against the restored data.

- [ ] **Step 7: Create and validate the post-migration backup**

Run `scripts/backup-local.sh` with the Archive root. Run `scripts/verify-backup.sh` on the emitted directory. Confirm its metadata matches the authoritative database and includes migration `002_location_verification`.

- [ ] **Step 8: Generate the private initial audit**

Run:

```bash
uv run partdb audit --output \
  "$ARCHIVE_ROOT/$(date -u +%Y-%m-%dT%H%M%SZ)-inventory-audit.md"
```

Review the report only for structural correctness: summary present, all finding sections render, and database counts match. Do not change inventory records during this task.

- [ ] **Step 9: Run the final local verification gate**

Run fresh:

```bash
uv sync --locked --all-extras
uv run ruff check .
uv run ruff format --check .
uv run pytest -v
docker compose ps
git status --short
```

Expected: install succeeds; lint and tests exit 0; database service is healthy; no real data or generated private report appears in Git status.

- [ ] **Step 10: Record cutover and commit only defect fixes**

If acceptance required source changes, add a regression test first, run the owning test and full gate, then commit the tested fix. Otherwise make no artificial acceptance commit. Record in the final handoff:

- Pre-cutover backup path and successful restore validation.
- Post-migration backup path and successful restore validation.
- Authoritative local counts and migration version.
- Audit report path.
- Confirmation that Euclid is no longer required for normal operation.
- Explicit statement that physical corrections and product-direction work have not begun.

## Whole-Branch Review Gate

After all tasks pass, invoke `superpowers:requesting-code-review` for a whole-branch review against the design spec and this plan. Resolve findings through tests, rerun the full Task 9 verification gate, and only then use `superpowers:finishing-a-development-branch` to choose merge/push integration.
