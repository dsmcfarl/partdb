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
