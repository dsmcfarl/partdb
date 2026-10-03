# PartDB

PartDB records which workshop parts are stored in which physical locations. It is intended for a personal workshop: a location has a unique name, several parts may share one location, and quantities are deliberately not tracked.

The CLI supports offline inventory work, PostgreSQL full-text search, optional semantic search, data-quality auditing, and explicit physical verification of bins.

## Local Setup

Requirements:

- Docker with Compose
- [`uv`](https://docs.astral.sh/uv/)
- [`just`](https://just.systems/) for the convenience recipes

Install the locked Python environment and start PostgreSQL 17 with pgvector:

```bash
uv sync --locked --all-extras
docker compose up -d --wait
uv run partdb db migrate
```

Or run:

```bash
just install
just up
```

The database is persisted in the stable Docker volume `partdb_partdb-data` and exposed only on `127.0.0.1:5435`. The Compose project is explicitly named `partdb`, so the same authoritative volume is used from a worktree or the canonical checkout. The default connection is:

```text
postgresql://partdb@127.0.0.1:5435/partdb
```

Override it for a command with `PARTDB_DSN`. The local Compose database uses trust authentication because it is loopback-only; do not expose its port beyond localhost.

Apply pending schema changes at any time with:

```bash
just migrate
```

## Inventory Commands

```bash
# Create a location or add a part
uv run partdb add 5A1
uv run partdb add 5A1 "part description"

# List inventory
uv run partdb list
uv run partdb list 5A1
uv run partdb list --locations

# Correct recorded inventory
uv run partdb update 42 "revised description"
uv run partdb move 42 5A2
uv run partdb delete --id 42
uv run partdb delete --location 5A1

# Offline PostgreSQL search
uv run partdb search --full-text "search phrase"
```

Deleting a populated location fails rather than cascading its parts. Locations must be created explicitly before parts can be moved into them.

### CSV Export and Import

```bash
uv run partdb dumpdb --path ./export
uv run partdb loaddb --path ./export
```

Exports contain `locations.csv` and `parts.csv`. They are useful for human inspection but do not contain embeddings; a PostgreSQL custom dump is the authoritative backup format.

## Optional Semantic Search

All ordinary inventory operations work without OpenAI. New or changed descriptions have no embedding until refreshed, preventing stale vectors from representing edited text.

Semantic search and refresh require the optional dependency (installed by `--all-extras`) and `PARTDB_OPENAI_API_KEY` in the environment, or `PARTDB_OPENAI_API_KEY_CMD` (a command that prints it, run only by semantic commands):

```bash
uv run partdb embeddings refresh
uv run partdb search "conceptual description"
```

Do not place API keys in the repository.

## Physical Inventory Verification

Display an inclusive, naturally ordered batch of bins:

```bash
uv run partdb inventory --from 5A1 --through 5A8
```

After physically checking the bins and recording any corrections, mark the confirmed locations:

```bash
uv run partdb verify mark 5A1 5A2
uv run partdb verify mark --from 5A1 --through 5A8
```

Mark a range only if nothing is recorded there, for bins confirmed empty:

```bash
uv run partdb verify mark --from 5A1 --through 5A8 --expect-empty
```

Undo an accidental mark and inspect progress:

```bash
uv run partdb verify clear 5A2
uv run partdb verify status              # summary line
uv run partdb verify status --unverified # remaining bins
uv run partdb verify status --all        # every bin with its status
```

Verification records only the latest confirmation timestamp. Correctly recorded adds, moves, updates, and deletes do not clear it.

## Applying a Reviewed Batch

Attended bin reviews are run by an agent following the `bin-review` skill in `.claude/skills/bin-review/`. The agent applies each table Dan approves with one atomic command:

```bash
uv run partdb apply plan.json --dry-run   # show the diff only
uv run partdb apply plan.json --yes       # apply in one transaction
uv run partdb apply - --yes < plan.json   # read the plan from stdin
```

A plan lists each bin's complete intended contents:

```json
{"verify": true,
 "bins": {
   "5A1": {"parts": [
             {"id": 12, "description": "M3 x 8 mm socket head screws"},
             {"id": 13},
             {"description": "M3 nylon standoffs"}],
           "remove": {"14": "delete", "15": {"move": "5A2"}}}}}
```

A `remove` move may add `"description"` to rename the part as it moves, without listing or verifying the destination bin. Every part recorded in a listed bin must be listed, removed, or listed in another bin of the same plan; otherwise the whole plan is rejected and nothing changes. `"verify": true` marks the listed bins verified in the same transaction, and `"create": true` on a bin creates it if it is missing. Search results label the nearest empty bins before and after each match, for example `nearest empty: 5A2 ↑ 5A4 ↓`.

## Private Data Audit

The audit is read-only and reports empty bins, suspicious descriptions, duplicates, naming inconsistencies, missing embeddings, invalid references, and verification totals:

```bash
uv run partdb audit
uv run partdb audit --output /private/path/inventory-audit.md
```

Reports contain real inventory descriptions. Store them outside this public repository.

## Backups

The default durable destination is:

```text
~/Documents/Archive/Interests/Workshop/PartDB/
```

Create a dated backup set containing a custom PostgreSQL dump, CSV exports, metadata, and SHA-256 checksums:

```bash
just backup
```

Backups always read the `partdb` database in the Compose `db` service; `PARTDB_DSN` does not change their source.

Validate checksums and perform a temporary restore before trusting a backup:

```bash
just verify-backup "/path/to/dated-backup"
```

`verify-backup` removes its disposable restore database even when validation fails. A backup restored under a newer pgvector image still verifies; the output reports both extension versions. Do not modify a completed dated backup directory.

## Recovery

With the Compose database running, restore a validated custom dump into an empty database:

```bash
docker compose exec -T db dropdb -U partdb --if-exists --force partdb
docker compose exec -T db createdb -U partdb partdb
docker compose exec -T db pg_restore -U partdb -d partdb \
  --no-owner --no-acl --exit-on-error < "/path/to/backup/partdb.custom"
uv run partdb db migrate
```

This replaces the current database. Run `verify-backup` and create a current backup before recovery.

## Development

```bash
just test
just lint
just format
```

GitHub Actions installs from `uv.lock`, starts the same Compose pgvector service, runs Ruff, and runs the complete pytest suite against disposable databases.
