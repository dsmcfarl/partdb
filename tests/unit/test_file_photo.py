import csv
import importlib.util
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".claude/skills/bin-review/scripts/file_photo.py"
HEADER = "file,original_name,taken_at,bin,part_ids,reviewed_on,note"


def load_script():
    spec = importlib.util.spec_from_file_location("file_photo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["file_photo"] = module
    spec.loader.exec_module(module)
    return module


file_photo = load_script()


def make_jpeg(
    path: Path, when: str | None = "2026:09:28 18:05:12", color=(200, 0, 0)
) -> Path:
    image = Image.new("RGB", (8, 8), color)
    exif = Image.Exif()
    if when is not None:
        exif.get_ifd(0x8769)[36867] = when
    image.save(path, "JPEG", exif=exif)
    return path


def read_manifest(root: Path) -> list[dict[str, str]]:
    with (root / "manifest.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    path = tmp_path / "Downloads"
    path.mkdir()
    return path


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "photos"
    monkeypatch.setenv("PARTDB_PHOTO_ROOT", str(path))
    return path


def test_files_multi_bin_photo_and_removes_original(
    downloads: Path, root: Path, capsys
) -> None:
    photo = make_jpeg(downloads / "IMG_6501.JPG")
    original = photo.read_bytes()

    code = file_photo.main(
        [str(photo), "--bin", "4A3=72,80", "--bin", "4A4=", "--note", "4A3 and 4A4"]
    )

    assert code == 0
    assert not photo.exists()
    for location in ("4A3", "4A4"):
        assert (root / location / "2026-09-28_IMG_6501.JPG").read_bytes() == original
    today = date.today().isoformat()  # noqa: DTZ011
    assert read_manifest(root) == [
        {
            "file": "4A3/2026-09-28_IMG_6501.JPG",
            "original_name": "IMG_6501.JPG",
            "taken_at": "2026-09-28T18:05:12",
            "bin": "4A3",
            "part_ids": "72;80",
            "reviewed_on": today,
            "note": "4A3 and 4A4",
        },
        {
            "file": "4A4/2026-09-28_IMG_6501.JPG",
            "original_name": "IMG_6501.JPG",
            "taken_at": "2026-09-28T18:05:12",
            "bin": "4A4",
            "part_ids": "",
            "reviewed_on": today,
            "note": "4A3 and 4A4",
        },
    ]
    assert (root / "manifest.csv").read_bytes().count(b"\r") == 0
    assert str(root / "4A3" / "2026-09-28_IMG_6501.JPG") in capsys.readouterr().out


def test_falls_back_to_mtime_without_exif(downloads: Path, root: Path) -> None:
    photo = make_jpeg(downloads / "IMG_1.JPG", when=None)
    stamp = datetime(2026, 9, 27, 17, 42, 27).timestamp()  # noqa: DTZ001
    os.utime(photo, (stamp, stamp))

    assert file_photo.main([str(photo), "--bin", "5A1=174", "--keep-original"]) == 0

    assert read_manifest(root)[0]["taken_at"] == "2026-09-27T17:42:27"
    assert (root / "5A1" / "2026-09-27_IMG_1.JPG").exists()
    assert photo.exists()


def test_rerun_is_idempotent(downloads: Path, root: Path) -> None:
    photo = make_jpeg(downloads / "IMG_6501.JPG")
    args = [str(photo), "--bin", "4A3=72", "--keep-original"]

    assert file_photo.main(args) == 0
    assert file_photo.main(args) == 0

    assert len(read_manifest(root)) == 1


def test_different_file_with_same_name_fails_without_changes(
    downloads: Path, root: Path, capsys
) -> None:
    existing = root / "4A3" / "2026-09-28_IMG_6501.JPG"
    existing.parent.mkdir(parents=True)
    make_jpeg(existing, color=(0, 0, 255))
    photo = make_jpeg(downloads / "IMG_6501.JPG")

    code = file_photo.main([str(photo), "--bin", "4A4=", "--bin", "4A3=72"])

    assert code == 1
    assert photo.exists()
    assert not (root / "4A4").exists()
    assert not (root / "manifest.csv").exists()
    assert "already exists with different content" in capsys.readouterr().err


def test_appends_after_manifest_without_trailing_newline(
    downloads: Path, root: Path
) -> None:
    root.mkdir()
    (root / "manifest.csv").write_text(
        f"{HEADER}\n5A1/x.JPG,x.JPG,2026-09-27T17:42:27,5A1,174,2026-09-27,old",
        encoding="utf-8",
    )
    photo = make_jpeg(downloads / "IMG_6501.JPG")

    assert file_photo.main([str(photo), "--bin", "4A3=72"]) == 0

    rows = read_manifest(root)
    assert [row["file"] for row in rows] == [
        "5A1/x.JPG",
        "4A3/2026-09-28_IMG_6501.JPG",
    ]
    assert rows[0]["note"] == "old"


def test_unexpected_manifest_columns_fail_before_copying(
    downloads: Path, root: Path
) -> None:
    root.mkdir()
    (root / "manifest.csv").write_text("file,bin\n", encoding="utf-8")
    photo = make_jpeg(downloads / "IMG_6501.JPG")

    assert file_photo.main([str(photo), "--bin", "4A3=72"]) == 1

    assert photo.exists()
    assert not (root / "4A3").exists()


@pytest.mark.parametrize(
    "bins",
    [
        ["--bin", "4A3"],
        ["--bin", "4A3=x"],
        ["--bin", "=1"],
        ["--bin", "../4A3=1"],
        ["--bin", "4A3=1", "--bin", "4a3=2"],
    ],
)
def test_rejects_bad_bin_arguments(downloads: Path, root: Path, bins) -> None:
    photo = make_jpeg(downloads / "IMG_6501.JPG")

    with pytest.raises(SystemExit) as excinfo:
        file_photo.main([str(photo), *bins])

    assert excinfo.value.code == 2
    assert photo.exists()
    assert not root.exists()


def test_empty_photo_root_falls_back_to_default_root(
    downloads: Path, tmp_path: Path, monkeypatch
) -> None:
    default_root = tmp_path / "default-photos"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setattr(file_photo, "DEFAULT_ROOT", default_root)
    monkeypatch.setenv("PARTDB_PHOTO_ROOT", "  ")
    monkeypatch.chdir(cwd)
    photo = make_jpeg(downloads / "IMG_7001.JPG")

    assert file_photo.main([str(photo), "--bin", "4A3=1"]) == 0

    assert (default_root / "4A3" / "2026-09-28_IMG_7001.JPG").exists()
    assert list(cwd.iterdir()) == []
