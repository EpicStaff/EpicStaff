import io
import json
import zipfile
from pathlib import Path

SAMPLES_DIR = Path(__file__).resolve().parent


def sample_files(sample: str = "chat-bot") -> dict[str, bytes]:
    """Every file of a sample plugin folder, keyed by its path inside the zip."""
    root = SAMPLES_DIR / sample
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def build_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def build_sample_zip(
    sample: str = "chat-bot",
    *,
    manifest_changes: dict | None = None,
    replace: dict[str, bytes | None] | None = None,
) -> bytes:
    """Zip a sample plugin in memory, optionally altered, for tests and manual installs.

    Args:
        manifest_changes: Top-level plugin.json keys to set; a value of None removes the key.
        replace: Zip paths to overwrite with new bytes; a value of None removes the file.
    """
    files = sample_files(sample)
    if manifest_changes:
        manifest = json.loads(files["plugin.json"])
        for key, value in manifest_changes.items():
            if value is None:
                manifest.pop(key, None)
            else:
                manifest[key] = value
        files["plugin.json"] = json.dumps(manifest).encode()
    for path, content in (replace or {}).items():
        if content is None:
            files.pop(path, None)
        else:
            files[path] = content
    return build_zip(files)
