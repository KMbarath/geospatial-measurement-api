"""Upload persistence on local disk."""
import re
import shutil
from pathlib import Path

from fastapi import UploadFile

from app.errors import FileTooLargeError

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
CHUNK = 1024 * 1024


def clean_filename(name: str | None) -> str:
    """Basename only, no path separators / control chars; never empty."""
    base = Path((name or "").replace("\\", "/")).name.strip()
    return base[:255] or "upload"


def safe_disk_name(name: str) -> str:
    stem = _SAFE.sub("_", Path(name).stem)[:100] or "upload"
    return f"{stem}{Path(name).suffix.lower()}"


def save_upload(upload: UploadFile, directory: Path, filename: str, max_bytes: int) -> tuple[Path, int]:
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / safe_disk_name(filename)
    written = 0
    try:
        with dest.open("wb") as out:
            while chunk := upload.file.read(CHUNK):
                written += len(chunk)
                if written > max_bytes:
                    raise FileTooLargeError(f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit.")
                out.write(chunk)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return dest, written


def delete_upload_dir(directory: Path) -> None:
    shutil.rmtree(directory, ignore_errors=True)
