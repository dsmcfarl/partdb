#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    printf 'usage: %s BACKUP_DIR\n' "$0" >&2
    exit 2
fi

repo=$(cd "$(dirname "$0")/.." && pwd)
dir=$1
[[ "$dir" == /* ]] || dir="$PWD/$dir"
required=(partdb.custom locations.csv parts.csv metadata.txt SHA256SUMS)
for name in "${required[@]}"; do
    if [[ ! -f "$dir/$name" ]]; then
        printf 'missing backup file: %s\n' "$name" >&2
        exit 1
    fi
done

(
    cd "$dir"
    shasum -a 256 -c SHA256SUMS >/dev/null
)
cd "$repo"
docker compose exec -T db pg_restore --list < "$dir/partdb.custom" >/dev/null

restore_db="partdb_restore_$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
cleanup() {
    docker compose exec -T db dropdb -U partdb --if-exists --force "$restore_db" \
        >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose exec -T db createdb -U partdb "$restore_db"
docker compose exec -T db pg_restore -U partdb -d "$restore_db" \
    --no-owner --no-acl --exit-on-error < "$dir/partdb.custom"

actual_locations=$(docker compose exec -T db psql -U partdb -d "$restore_db" -Atqc \
    'SELECT count(*) FROM locations')
actual_parts=$(docker compose exec -T db psql -U partdb -d "$restore_db" -Atqc \
    'SELECT count(*) FROM parts')
actual_embeddings=$(docker compose exec -T db psql -U partdb -d "$restore_db" -Atqc \
    'SELECT count(*) FROM parts WHERE embedding IS NOT NULL')
actual_vector=$(docker compose exec -T db psql -U partdb -d "$restore_db" -Atqc \
    "SELECT extversion FROM pg_extension WHERE extname='vector'")
actual_migration=$(docker compose exec -T db psql -U partdb -d "$restore_db" -Atqc \
    "SELECT coalesce(max(version), 'none') FROM schema_migrations")
expected_locations=$(awk -F= '$1 == "locations" {print $2}' "$dir/metadata.txt")
expected_parts=$(awk -F= '$1 == "parts" {print $2}' "$dir/metadata.txt")
expected_embeddings=$(awk -F= '$1 == "embeddings" {print $2}' "$dir/metadata.txt")
expected_vector=$(awk -F= '$1 == "vector" {print $2}' "$dir/metadata.txt")
expected_migration=$(awk -F= '$1 == "migration" {print $2}' "$dir/metadata.txt")

if [[ "$actual_locations" != "$expected_locations" ]]; then
    printf 'location count mismatch: expected %s, restored %s\n' \
        "$expected_locations" "$actual_locations" >&2
    exit 1
fi
if [[ "$actual_parts" != "$expected_parts" ]]; then
    printf 'part count mismatch: expected %s, restored %s\n' \
        "$expected_parts" "$actual_parts" >&2
    exit 1
fi
if [[ "$actual_embeddings" != "$expected_embeddings" ]]; then
    printf 'embedding count mismatch: expected %s, restored %s\n' \
        "$expected_embeddings" "$actual_embeddings" >&2
    exit 1
fi
if [[ "$actual_migration" != "$expected_migration" ]]; then
    printf 'migration mismatch: expected %s, restored %s\n' \
        "$expected_migration" "$actual_migration" >&2
    exit 1
fi

printf 'locations=%s\n' "$actual_locations"
printf 'parts=%s\n' "$actual_parts"
printf 'embeddings=%s\n' "$actual_embeddings"
# pg_restore installs the server's current pgvector, so report version drift only.
if [[ "$actual_vector" == "$expected_vector" ]]; then
    printf 'vector=%s\n' "$actual_vector"
else
    printf 'vector=%s (backup %s)\n' "$actual_vector" "$expected_vector"
fi
printf 'migration=%s\n' "$actual_migration"
