import select
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WATCHER = REPO / ".claude/skills/bin-review/scripts/watch_downloads.sh"


def read_line(process: subprocess.Popen, timeout: float) -> str | None:
    ready, _, _ = select.select([process.stdout], [], [], timeout)
    if not ready:
        return None
    return process.stdout.readline().strip()


def start(watched: Path, state: Path) -> subprocess.Popen:
    process = subprocess.Popen(
        ["bash", str(WATCHER), str(watched), str(state)],
        stdout=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not state.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return process


def test_reports_each_new_photo_once_across_restarts(tmp_path: Path) -> None:
    watched = tmp_path / "Downloads"
    watched.mkdir()
    (watched / "old.JPG").write_bytes(b"existing")
    state = tmp_path / "seen.txt"

    process = start(watched, state)
    try:
        (watched / "notes.txt").write_text("not a photo")
        (watched / "IMG_1.JPG").write_bytes(b"photo")
        assert read_line(process, 6) == f"NEW PHOTO: {watched / 'IMG_1.JPG'}"
    finally:
        process.terminate()
        process.wait()

    (watched / "IMG_2.heic").write_bytes(b"arrived while stopped")
    process = start(watched, state)
    try:
        assert read_line(process, 6) == f"NEW PHOTO: {watched / 'IMG_2.heic'}"
        assert read_line(process, 3) is None
    finally:
        process.terminate()
        process.wait()
