#!/usr/bin/env bash
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
root=${1:-"$HOME/Documents/Archive/Interests/Workshop/PartDB"}
stamp=${PARTDB_BACKUP_TIMESTAMP:-$(date -u +%Y-%m-%dT%H%M%SZ)}
database=${PARTDB_DATABASE:-partdb}
dsn=${PARTDB_DSN:-postgresql://partdb@127.0.0.1:5435/$database}
dest="$root/$stamp-local"
tmp="$dest.incomplete"

if [[ -e "$dest" || -e "$tmp" ]]; then
    printf 'backup destination already exists: %s\n' "$dest" >&2
    exit 1
fi

trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp"
cd "$repo"

docker compose exec -T db pg_dump -U partdb -d "$database" \
    --format=custom --no-owner --no-acl > "$tmp/partdb.custom"
PARTDB_DSN="$dsn" uv run partdb dumpdb --path "$tmp" >/dev/null

docker compose exec -T db psql -U partdb -d "$database" -At <<'SQL' \
    > "$tmp/metadata.txt"
SELECT 'postgres=' || version();
SELECT 'vector=' || extversion FROM pg_extension WHERE extname='vector';
SELECT 'locations=' || count(*) FROM locations;
SELECT 'parts=' || count(*) FROM parts;
SELECT 'embeddings=' || count(*) FROM parts WHERE embedding IS NOT NULL;
SELECT 'migration=' || coalesce(max(version), 'none') FROM schema_migrations;
SQL

(
    cd "$tmp"
    shasum -a 256 partdb.custom locations.csv parts.csv metadata.txt > SHA256SUMS
)
mv "$tmp" "$dest"
trap - EXIT
printf '%s\n' "$dest"
