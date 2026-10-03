#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=11"]
# ///
"""File a bin-review photo into the PartDB photo archive with manifest rows."""

import argparse
import csv
import hashlib
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from PIL import Image

DEFAULT_ROOT = Path.home() / "Documents/Archive/Interests/Workshop/PartDB/photos"
FIELDS = ["file", "original_name", "taken_at", "bin", "part_ids", "reviewed_on", "note"]
EXIF_IFD = 0x8769
DATE_TIME_ORIGINAL = 36867


class FilingError(Exception):
    """The photo could not be filed. The original is left in place."""


@dataclass(frozen=True)
class BinTarget:
    location: str
    part_ids: tuple[int, ...]


def parse_bin(value: str) -> BinTarget:
    location, separator, ids = value.partition("=")
    location = location.strip()
    if not separator or not location:
        raise argparse.ArgumentTypeError(f"expected LOCATION=IDS, got {value!r}")
    if "/" in location or "\\" in location or location in {".", ".."}:
        raise argparse.ArgumentTypeError(f"invalid location {location!r}")
    try:
        part_ids = tuple(int(item) for item in ids.split(",") if item.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"part ids must be integers, got {ids!r}"
        ) from None
    return BinTarget(location, part_ids)


def taken_at(path: Path) -> datetime:
    try:
        with Image.open(path) as image:
            raw = image.getexif().get_ifd(EXIF_IFD).get(DATE_TIME_ORIGINAL)
    except OSError:
        raw = None
    if raw:
        try:
            return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")  # noqa: DTZ007
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime).replace(  # noqa: DTZ006
        microsecond=0
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def existing_rows(manifest: Path) -> set[tuple[str, ...]]:
    if not manifest.exists():
        return set()
    with manifest.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != FIELDS:
            raise FilingError(
                f"{manifest} has columns {reader.fieldnames}, expected {FIELDS}"
            )
        return {tuple(row[field] for field in FIELDS) for row in reader}


def append_rows(manifest: Path, rows: list[dict[str, str]], seen) -> None:
    new_file = not manifest.exists()
    needs_newline = (
        not new_file
        and manifest.stat().st_size > 0
        and not manifest.read_bytes().endswith(b"\n")
    )
    with manifest.open("a", newline="", encoding="utf-8") as handle:
        if needs_newline:
            handle.write("\n")
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        if new_file:
            writer.writeheader()
        for row in rows:
            if tuple(row[field] for field in FIELDS) not in seen:
                writer.writerow(row)


def file_photo(
    source: Path,
    bins: list[BinTarget],
    note: str,
    root: Path,
    keep_original: bool,
) -> list[Path]:
    if not source.is_file():
        raise FilingError(f"{source} is not a file")
    manifest = root / "manifest.csv"
    seen = existing_rows(manifest)
    when = taken_at(source)
    digest = sha256(source)
    name = f"{when.date().isoformat()}_{source.name}"
    destinations = [root / target.location / name for target in bins]
    for destination in destinations:
        if destination.exists() and sha256(destination) != digest:
            raise FilingError(f"{destination} already exists with different content")
    for destination in destinations:
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".partial")
        shutil.copy2(source, partial)
        if sha256(partial) != digest:
            partial.unlink()
            raise FilingError(f"checksum mismatch copying to {destination}")
        partial.replace(destination)
    reviewed_on = date.today().isoformat()  # noqa: DTZ011
    rows = [
        {
            "file": f"{target.location}/{name}",
            "original_name": source.name,
            "taken_at": when.isoformat(),
            "bin": target.location,
            "part_ids": ";".join(str(part_id) for part_id in target.part_ids),
            "reviewed_on": reviewed_on,
            "note": note,
        }
        for target in bins
    ]
    append_rows(manifest, rows, seen)
    if not keep_original:
        source.unlink()
    return destinations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("photo", type=Path)
    parser.add_argument(
        "--bin",
        dest="bins",
        action="append",
        type=parse_bin,
        required=True,
        metavar="LOCATION=IDS",
        help="bin shown in the photo and the part ids it shows (repeatable)",
    )
    parser.add_argument("--note", default="", help="short description of the shot")
    parser.add_argument(
        "--keep-original", action="store_true", help="do not remove the source file"
    )
    args = parser.parse_args(argv)
    locations = [target.location.casefold() for target in args.bins]
    if len(set(locations)) != len(locations):
        parser.error("each bin may be given only once")
    root = Path(os.environ.get("PARTDB_PHOTO_ROOT", DEFAULT_ROOT)).expanduser()
    try:
        destinations = file_photo(
            args.photo.expanduser(), args.bins, args.note, root, args.keep_original
        )
    except (FilingError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for destination in destinations:
        print(destination)
    return 0


if __name__ == "__main__":
    sys.exit(main())
