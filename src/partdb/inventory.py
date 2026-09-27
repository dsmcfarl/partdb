import csv
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from partdb.embeddings import EmbeddingProvider
from partdb.errors import (
    DuplicateLocation,
    InvalidLocationRange,
    LocationNotEmpty,
    LocationNotFound,
    PartNotFound,
)
from partdb.location_order import inclusive_location_range, natural_location_key
from partdb.models import InventoryLocation, Location, Part, SearchResult


class InventoryService:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def list_locations(self) -> list[Location]:
        rows = self.conn.execute("SELECT name, verified_at FROM locations")
        locations = [Location(row[0], row[1]) for row in rows]
        return sorted(locations, key=lambda item: natural_location_key(item.name))

    def list_parts(self, location: str | None = None) -> list[Part]:
        if location is None:
            rows = self.conn.execute(
                """SELECT id, location, description, embedding IS NOT NULL
                FROM parts"""
            )
        else:
            self._require_location(location)
            rows = self.conn.execute(
                """SELECT id, location, description, embedding IS NOT NULL
                FROM parts WHERE location = %s ORDER BY description, id""",
                (location,),
            )
        parts = [self._part(row) for row in rows]
        if location is None:
            return sorted(
                parts,
                key=lambda item: (
                    natural_location_key(item.location),
                    item.description,
                    item.id,
                ),
            )
        return parts

    def get_part(self, part_id: int) -> Part:
        row = self.conn.execute(
            """SELECT id, location, description, embedding IS NOT NULL
            FROM parts WHERE id = %s""",
            (part_id,),
        ).fetchone()
        if row is None:
            raise PartNotFound(f"part {part_id} not found")
        return self._part(row)

    def part_count(self) -> int:
        return self.conn.execute("SELECT count(*) FROM parts").fetchone()[0]

    def add_location(self, name: str) -> Location:
        name = self._nonblank(name, "location")
        collision = self.conn.execute(
            "SELECT name FROM locations WHERE lower(name) = lower(%s) LIMIT 1",
            (name,),
        ).fetchone()
        if collision is not None:
            raise DuplicateLocation(f"location {name} already exists")
        row = self.conn.execute(
            """INSERT INTO locations(name) VALUES (%s)
            ON CONFLICT DO NOTHING RETURNING name, verified_at""",
            (name,),
        ).fetchone()
        if row is None:
            raise DuplicateLocation(f"location {name} already exists")
        return Location(row[0], row[1])

    def add_part(self, location: str, description: str) -> Part:
        location = self._nonblank(location, "location")
        description = self._nonblank(description, "description")
        self._require_location(location)
        row = self.conn.execute(
            """INSERT INTO parts(location, description, embedding)
            VALUES (%s, %s, NULL)
            RETURNING id, location, description, embedding IS NOT NULL""",
            (location, description),
        ).fetchone()
        return self._part(row)

    def update_part(self, part_id: int, description: str) -> Part:
        description = self._nonblank(description, "description")
        row = self.conn.execute(
            """UPDATE parts SET description = %s, embedding = NULL
            WHERE id = %s
            RETURNING id, location, description, embedding IS NOT NULL""",
            (description, part_id),
        ).fetchone()
        if row is None:
            raise PartNotFound(f"part {part_id} not found")
        return self._part(row)

    def move_part(self, part_id: int, location: str) -> Part:
        location = self._nonblank(location, "location")
        self._require_location(location)
        row = self.conn.execute(
            """UPDATE parts SET location = %s WHERE id = %s
            RETURNING id, location, description, embedding IS NOT NULL""",
            (location, part_id),
        ).fetchone()
        if row is None:
            raise PartNotFound(f"part {part_id} not found")
        return self._part(row)

    def delete_part(self, part_id: int) -> None:
        row = self.conn.execute(
            "DELETE FROM parts WHERE id = %s RETURNING id", (part_id,)
        ).fetchone()
        if row is None:
            raise PartNotFound(f"part {part_id} not found")

    def delete_location(self, name: str) -> None:
        name = self._nonblank(name, "location")
        self._require_location(name)
        has_parts = self.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM parts WHERE location = %s)", (name,)
        ).fetchone()[0]
        if has_parts:
            raise LocationNotEmpty(f"location {name} is not empty")
        self.conn.execute("DELETE FROM locations WHERE name = %s", (name,))

    def inventory_range(self, start: str, end: str) -> list[InventoryLocation]:
        names = [location.name for location in self.list_locations()]
        selected = inclusive_location_range(names, start, end)
        return self.inventory_locations(selected)

    def inventory_locations(self, names: Sequence[str]) -> list[InventoryLocation]:
        canonical = self._canonical_location_names(names)
        locations = {location.name: location for location in self.list_locations()}
        return [
            InventoryLocation(
                name=name,
                verified_at=locations[name].verified_at,
                parts=tuple(self.list_parts(name)),
            )
            for name in canonical
        ]

    def mark_verified(
        self, names: Sequence[str], verified_at: datetime | None = None
    ) -> int:
        canonical = self._canonical_location_names(names)
        timestamp = verified_at or datetime.now(UTC)
        result = self.conn.execute(
            "UPDATE locations SET verified_at = %s WHERE name = ANY(%s)",
            (timestamp, canonical),
        )
        return result.rowcount

    def clear_verification(self, names: Sequence[str]) -> int:
        canonical = self._canonical_location_names(names)
        result = self.conn.execute(
            "UPDATE locations SET verified_at = NULL WHERE name = ANY(%s)",
            (canonical,),
        )
        return result.rowcount

    def verification_status(self, unverified_only: bool = False) -> list[Location]:
        locations = self.list_locations()
        if unverified_only:
            locations = [item for item in locations if item.verified_at is None]
        return sorted(locations, key=lambda item: natural_location_key(item.name))

    def search_full_text(self, description: str) -> list[SearchResult]:
        description = self._nonblank(description, "description")
        rows = self.conn.execute(
            """SELECT id, location, description, NULL::double precision
            FROM parts
            WHERE to_tsvector('english', description)
                @@ websearch_to_tsquery('english', %s)""",
            (description,),
        )
        results = self._search_results(rows)
        return sorted(
            results,
            key=lambda item: (
                natural_location_key(item.location),
                item.description,
                item.id,
            ),
        )

    def search_semantic(
        self, provider: EmbeddingProvider, description: str, limit: int = 10
    ) -> list[SearchResult]:
        description = self._nonblank(description, "description")
        if limit < 1:
            raise ValueError("limit must be positive")
        vector = self._vector_literal(provider.embed(description))
        rows = self.conn.execute(
            """SELECT id, location, description,
                embedding <=> %s::vector AS distance
            FROM parts
            WHERE embedding IS NOT NULL
            ORDER BY distance, id LIMIT %s""",
            (vector, limit),
        )
        return self._search_results(rows)

    def refresh_embeddings(
        self, provider: EmbeddingProvider, refresh_all: bool = False
    ) -> int:
        query = "SELECT id, description FROM parts"
        if not refresh_all:
            query += " WHERE embedding IS NULL"
        rows = list(self.conn.execute(query + " ORDER BY id"))
        for part_id, description in rows:
            vector = self._vector_literal(provider.embed(description))
            self.conn.execute(
                "UPDATE parts SET embedding = %s::vector WHERE id = %s",
                (vector, part_id),
            )
        return len(rows)

    def dump_csv(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        with (path / "locations.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["name"])
            writer.writerows((location.name,) for location in self.list_locations())
        with (path / "parts.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["location", "description"])
            writer.writerows(
                (part.location, part.description) for part in self.list_parts()
            )

    def load_csv(self, path: Path) -> None:
        locations = self._read_csv(path / "locations.csv", ["name"])
        parts = self._read_csv(path / "parts.csv", ["location", "description"])
        names: list[str] = []
        names_by_casefold: set[str] = set()
        for row in locations:
            name = self._nonblank(row["name"], "location")
            if name.casefold() in names_by_casefold:
                raise ValueError(f"duplicate location {name}")
            names.append(name)
            names_by_casefold.add(name.casefold())
        existing = {location.name.casefold() for location in self.list_locations()}
        duplicate = existing.intersection(names_by_casefold)
        if duplicate:
            original = next(name for name in names if name.casefold() in duplicate)
            raise ValueError(f"duplicate location {original}")
        prepared_parts: list[tuple[str, str]] = []
        for row in parts:
            location = self._nonblank(row["location"], "location")
            description = self._nonblank(row["description"], "description")
            if location not in names:
                raise ValueError(f"unknown location {location}")
            prepared_parts.append((location, description))
        for name in names:
            self.add_location(name)
        for location, description in prepared_parts:
            self.add_part(location, description)

    @staticmethod
    def _read_csv(path: Path, fields: list[str]) -> list[dict[str, str]]:
        if not path.is_file():
            raise ValueError(f"missing {path.name}")
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != fields:
                raise ValueError(f"{path.name} headers must be {','.join(fields)}")
            rows = list(reader)
        if any(None in row or None in row.values() for row in rows):
            raise ValueError(f"malformed row in {path.name}")
        return rows

    @staticmethod
    def _vector_literal(values: list[float]) -> str:
        if len(values) != 1536:
            raise ValueError("embedding must contain exactly 1536 values")
        return "[" + ",".join(str(float(value)) for value in values) + "]"

    def _search_results(self, rows: Iterable[tuple]) -> list[SearchResult]:
        rows = list(rows)
        names = [item.name for item in self.list_locations()]
        occupied = {
            row[0] for row in self.conn.execute("SELECT DISTINCT location FROM parts")
        }
        results = []
        for row in rows:
            index = names.index(row[1])
            previous_empty = next(
                (name for name in reversed(names[:index]) if name not in occupied),
                None,
            )
            next_empty = next(
                (name for name in names[index + 1 :] if name not in occupied), None
            )
            results.append(
                SearchResult(
                    id=row[0],
                    location=row[1],
                    description=row[2],
                    distance=float(row[3]) if row[3] is not None else None,
                    previous_empty=previous_empty,
                    next_empty=next_empty,
                )
            )
        return results

    def _canonical_location_names(self, names: Sequence[str]) -> list[str]:
        if not names:
            raise InvalidLocationRange("at least one location is required")
        by_casefold: dict[str, list[str]] = {}
        for location in self.list_locations():
            by_casefold.setdefault(location.name.casefold(), []).append(location.name)
        canonical: list[str] = []
        for name in names:
            matches = by_casefold.get(name.casefold(), [])
            if not matches:
                raise LocationNotFound(f"location {name} not found")
            if name in matches:
                selected = name
            elif len(matches) > 1:
                raise InvalidLocationRange(f"ambiguous location {name}")
            else:
                selected = matches[0]
            if selected not in canonical:
                canonical.append(selected)
        return sorted(canonical, key=natural_location_key)

    def _require_location(self, name: str) -> None:
        exists = self.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM locations WHERE name = %s)", (name,)
        ).fetchone()[0]
        if not exists:
            raise LocationNotFound(f"location {name} not found")

    @staticmethod
    def _nonblank(value: str, field: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{field} cannot be blank")
        return value

    @staticmethod
    def _part(row: tuple) -> Part:
        return Part(
            id=row[0],
            location=row[1],
            description=row[2],
            has_embedding=row[3],
        )
