from dataclasses import dataclass
from datetime import datetime


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


@dataclass(frozen=True)
class SearchResult:
    id: int
    location: str
    description: str
    distance: float | None
    previous_empty: str | None
    next_empty: str | None


@dataclass(frozen=True)
class InventoryLocation:
    name: str
    verified_at: datetime | None
    parts: tuple[Part, ...]
