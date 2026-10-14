"""
File storage backend. LocalStorage writes under UPLOAD_DIR; swap in an S3-compatible
backend by implementing the same three methods.
"""
import os
from pathlib import Path


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid storage key")
        return path

    def save(self, key: str, content: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return key

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()


storage = LocalStorage(os.getenv("UPLOAD_DIR", "uploads"))

# Allowed upload types, recognised by their leading bytes (not the client-supplied header).
_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"%PDF-", "application/pdf"),
)


def detect_content_type(content: bytes) -> str | None:
    for signature, content_type in _SIGNATURES:
        if content.startswith(signature):
            return content_type
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    # Audio (voice notes for the assistant).
    if content[:4] == b"RIFF" and content[8:12] == b"WAVE":
        return "audio/wav"
    if content.startswith(b"OggS"):
        return "audio/ogg"
    if content.startswith(b"ID3") or content[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if content[4:8] == b"ftyp" and content[8:12] in (b"M4A ", b"mp42", b"isom"):
        return "audio/mp4"
    if content.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm"
    return None
