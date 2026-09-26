import psycopg

from partdb.errors import (
    DuplicateLocation,
    LocationNotEmpty,
    LocationNotFound,
    PartNotFound,
)
from partdb.models import Location, Part


class InventoryService:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def list_locations(self) -> list[Location]:
        rows = self.conn.execute(
            "SELECT name, verified_at FROM locations ORDER BY name"
        )
        return [Location(row[0], row[1]) for row in rows]

    def list_parts(self, location: str | None = None) -> list[Part]:
        if location is None:
            rows = self.conn.execute(
                """SELECT id, location, description, embedding IS NOT NULL
                FROM parts ORDER BY location, description, id"""
            )
        else:
            self._require_location(location)
            rows = self.conn.execute(
                """SELECT id, location, description, embedding IS NOT NULL
                FROM parts WHERE location = %s ORDER BY description, id""",
                (location,),
            )
        return [self._part(row) for row in rows]

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
