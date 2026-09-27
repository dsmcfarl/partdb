# PartDB Local Revival Design

**Date:** 2026-09-26
**Status:** Approved

## Purpose

Revive PartDB as a dependable local application using the real workshop inventory, remove its operational dependency on the deprecated Euclid server, and establish a safe workflow for physically verifying bins over time.

This phase ends with a working and tested local CLI, an authoritative local PostgreSQL database, durable Archive backups, a read-only data-quality audit, and verification tracking. Product-direction work such as a web interface, mobile interface, or agent-oriented interaction is explicitly deferred until this foundation is complete.

## Current State

The canonical codebase is the public `dsmcfarl/partdb` repository. It is a Python Click CLI using psycopg, PostgreSQL, pgvector, and optional OpenAI embeddings. Its last commit was on 2024-11-26.

Euclid currently holds the only active database:

- PostgreSQL 17 with pgvector 0.7.4
- 195 locations
- 201 parts
- 201 populated embeddings

A fresh checkout can read, search, and export this database. The installed Euclid CLI is broken because it was installed in editable mode and points to a deleted source checkout. Euclid has a recent custom-format database dump, but the revived system must not rely on Euclid for application operation or backup retention.

The existing repository has no tests, CI, schema migration mechanism, or reliable modern packaging. Most behavior is implemented in one module.

## Success Criteria

The phase is complete when:

1. The real inventory is restored into a Mac-hosted PostgreSQL/pgvector database and declared authoritative.
2. Immutable migration backups and a post-migration backup are stored outside Git under `~/Documents/Archive/`.
3. Backup integrity and local restoration are verified.
4. A clean checkout can install and run `partdb` using documented commands.
5. The local CLI supports the existing inventory operations without requiring OpenAI.
6. Full-text search, optional semantic search, schema migrations, physical verification tracking, and data auditing work and are tested.
7. CI passes against an ephemeral pgvector database.
8. A read-only audit report of the migrated inventory is available for review.
9. Euclid is unnecessary for normal operation.

## Non-Goals

This phase will not:

- Build a web, mobile, or natural-language interface.
- Revive the archived Django `partloc` project.
- Perform bulk corrections to inventory records.
- Automatically infer whether a physical bin is accurate.
- Store inventory data, database dumps, CSV exports, or credentials in the public Git repository.
- Add verification history beyond the latest verification timestamp.
- Automatically invalidate verification when correctly recorded inventory operations occur.

## Architecture

### Repository and Runtime

The repository lives at `~/code/gh/dsmcfarl/partdb`. Development occurs in an isolated Git worktree. The committed development environment includes a `compose.yaml` running a pinned `pgvector/pgvector` PostgreSQL image.

PostgreSQL binds only to localhost and stores its authoritative data in a persistent Docker volume. The local-only Compose service uses trust authentication so no database password must be stored; it must never be exposed beyond the loopback interface. Any future external credentials remain outside Git.

The Python project uses `uv` with a valid build backend and lockfile. A clean `uv sync --locked` installs the `partdb` console command.

### Application Modules

The current monolithic implementation is separated into focused modules:

- `cli.py`: Click commands, argument validation, confirmation, and human-readable output.
- `inventory.py`: inventory, search, and location-verification operations.
- `database.py`: connections, transactions, and low-level database infrastructure.
- `embeddings.py`: optional OpenAI embedding generation and refresh.
- `audit.py`: read-only data-quality analysis and report models.
- `migrations/`: ordered, versioned SQL schema migrations.

The modules retain psycopg and direct SQL. This phase does not introduce an ORM or application framework.

### Configuration

Database configuration is accepted through a documented environment variable or libpq-compatible connection configuration. Developer defaults point to the localhost-only Compose service. OpenAI configuration is optional and required only for semantic-query embedding generation and explicit embedding refresh.

## Data Migration and Cutover

The migration follows this sequence:

1. Create a fresh PostgreSQL custom-format dump of `partdb` on Euclid.
2. Create CSV exports of locations and parts as a human-inspectable secondary backup.
3. Record SHA-256 checksums and source row counts.
4. Copy the dump, exports, checksum manifest, and minimal metadata into a dated directory under `~/Documents/Archive/`.
5. Start the local Compose database from an empty persistent volume.
6. Restore the custom-format dump locally.
7. Apply repository-managed schema migrations, including verification tracking.
8. Compare source and destination location counts, part counts, populated embedding counts, and representative query results.
9. Run CLI smoke tests against the restored data without modifying it.
10. Create a post-migration custom-format backup and checksum manifest in the Archive.
11. Verify that the post-migration backup is readable and can be restored into a temporary database.
12. Declare the Mac database authoritative. Euclid is no longer required.

Backups are immutable, date-stamped artifacts. Inventory data remains outside the public repository. The exact Archive destination is selected using the established Archive filing conventions during implementation.

## Schema Management

A `schema_migrations` table records each applied migration. Migrations execute in order and inside transactions when PostgreSQL permits. Re-running the migration command is safe and does not reapply completed migrations.

The Euclid schema is treated as the baseline. The first new migration adds this nullable column:

```sql
ALTER TABLE locations ADD COLUMN verified_at TIMESTAMPTZ NULL;
```

`verified_at IS NULL` means the location has not been physically verified. A timestamp records the latest explicit physical confirmation. Historical verification events are not retained.

Correctly recorded adds, updates, moves, and deletes do not clear `verified_at`. Physical mismatch is expected to arise from workshop activity that was not entered into the system, not from recorded operations.

## CLI Behavior

Existing command concepts remain available: adding locations and parts, listing, searching, moving, updating, deleting, importing, exporting, and database administration. Command naming may be normalized during implementation, but backward-compatible aliases are retained where practical and covered by tests.

### Offline Inventory Operations

List, add, update, move, delete, full-text search, export, audit, and verification work without OpenAI.

When a part is added or its description changes without embedding generation, its `embedding` is set to `NULL`. This prevents stale vectors from representing changed text. Semantic search excludes rows with missing embeddings and explains when query embedding cannot be generated because OpenAI is not configured.

Missing embeddings can be refreshed explicitly:

```bash
partdb embeddings refresh
```

### Physical Inventory Workflow

Location ordering is natural and case-insensitive. Inclusive ranges such as `5A1` through `5A8` contain the expected physical sequence rather than lexical ordering such as `5A1`, `5A10`, `5A2`.

The CLI provides these workflows:

```bash
partdb inventory --from 5A1 --through 5A8
partdb verify mark 5A1 5A2
partdb verify mark --from 5A1 --through 5A8
partdb verify clear 5A3
partdb verify status
partdb verify status --unverified
```

`inventory` displays each requested location, its verification state, and its parts. Empty locations are included.

Range verification first displays every affected location and requires confirmation. A noninteractive confirmation option may be used by automation but must be explicit. Corrections use ordinary inventory commands. The operator marks a location verified only after confirming it or completing its corrections.

`verify clear` reverses an accidental verification. Verification progress reports total, verified, and unverified locations and can list unverified locations in natural order.

## Initial Data Audit

The audit is read-only. It detects and reports:

- Empty locations and locations without parts.
- Empty or whitespace-only part descriptions.
- Exact duplicate descriptions.
- Normalized duplicate descriptions, ignoring superficial case and whitespace differences.
- Location naming and case inconsistencies.
- Missing embeddings.
- Orphaned records or broken location references.
- Counts of verified and unverified locations.

The audit command exits successfully when the database is readable, even when findings exist. Findings are categorized by severity and summarized. Operational failures such as database connection errors return a nonzero exit.

The initial report is written outside the public repository because it contains real inventory descriptions. It does not modify records. Data corrections occur only after the user reviews the report and begins the physical-inventory process.

## Safety and Error Handling

- Every modifying command uses a transaction.
- Missing locations and parts produce clear messages and nonzero exit statuses.
- Moving a part to an unknown location fails; location creation must be explicit.
- Destructive commands require confirmation unless an explicit noninteractive flag is supplied.
- Range endpoints must exist, and reversed or ambiguous ranges fail without changing data.
- Backup and restore scripts stop on the first error and emit checksums and row-count evidence.
- PostgreSQL is not exposed beyond localhost.
- Credentials and real data are ignored by Git.

## Backup Strategy

The Archive is the durable backup destination selected by the user. Each backup set contains:

- A PostgreSQL custom-format dump.
- `locations.csv` and `parts.csv` when applicable.
- A SHA-256 checksum manifest.
- Metadata recording timestamp, database/server versions, schema migration version, and row counts.

The migration produces both pre-cutover and post-migration backup sets. Repository commands document and automate future dated backups, but backup artifacts themselves remain outside Git.

A backup is not considered verified merely because `pg_dump` exits successfully. Verification includes listing its contents and restoring it into a temporary database, then checking schema and row counts.

## Testing Strategy

### Unit Tests

Unit tests cover:

- Natural location parsing, comparison, and inclusive ranges.
- CLI argument validation and output formatting.
- Audit normalization and finding classification.
- Optional embedding behavior.

### Integration Tests

Integration tests run against an ephemeral PostgreSQL/pgvector database and cover:

- Baseline schema creation and migration from the Euclid schema.
- Migration idempotency.
- CRUD operations and transaction rollback.
- Full-text search.
- CSV dump/load compatibility.
- Natural inventory ranges.
- Verification mark, clear, status, and confirmation behavior.
- Audit queries and representative findings.
- Nulling stale embeddings and refreshing missing embeddings with a fake embedding provider.
- CLI installation and console entry point behavior.

### CI and Acceptance

GitHub Actions starts a pgvector service and runs formatting, linting, and the complete test suite from the locked environment.

Local acceptance additionally verifies:

- Clean setup from the documented commands.
- Real-data restore.
- Matching source and destination counts.
- Existing embedding preservation.
- Representative list and full-text searches.
- Successful generation and test restoration of a post-migration backup.
- Generation of the private initial audit report.

## Delivery Boundary and Next Phase

After acceptance, implementation stops. The next conversation brainstorms product direction and iterates on the human workflow for physically reviewing batches of bins. The first expected workflow is to request a range such as `5A1` through `5A8`, review displayed contents, provide corrections where necessary, and explicitly confirm verified locations.

No interface beyond the stabilized CLI is selected by this design. The modular boundaries preserve the option to add a web UI, mobile workflow, or agent integration later without replacing the inventory and database layers.
