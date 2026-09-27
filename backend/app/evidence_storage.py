"""Evidence storage abstraction.

Business logic talks only to `EvidenceStorage`; it never sees a filesystem path. The API exposes an opaque evidence
id (`ev_...`), never the storage key. To move to S3 / Azure Blob / GCS / municipal object storage, implement the
four methods below and register it in BACKENDS - no change to the evidence or audit workflow is needed:

    class S3EvidenceStorage:                       # sketch, NOT implemented in this repo
        def put(self, key, fileobj): s3.upload_fileobj(fileobj, bucket, key, ExtraArgs={"ServerSideEncryption": "AES256"})
        def open(self, key):         return s3.get_object(Bucket=bucket, Key=key)["Body"]
        def exists(self, key): ...
        def delete(self, key): ...

`delete` exists ONLY for rolling back an upload whose database write failed. It is not reachable from any API and
retention/erasure needs an explicit administrative policy (see README).
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO, Protocol

from . import settings

_KEY_RE = re.compile(r"^evidence/[0-9a-f]{2}/[0-9a-f]{32}$")


class EvidenceStorage(Protocol):
    backend: str

    def new_key(self) -> str: ...
    def put(self, key: str, fileobj: BinaryIO) -> int: ...
    def open(self, key: str) -> BinaryIO: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...


class LocalEvidenceStorage:
    """Prototype backend: files under one root directory, named only by server-generated keys."""
    backend = "local"

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def new_key(self) -> str:
        u = uuid.uuid4().hex
        return f"evidence/{u[:2]}/{u}"

    def _path(self, key: str) -> Path:
        if not _KEY_RE.match(key):
            raise ValueError("invalid storage key")
        p = (self.root / key).resolve()
        if self.root not in p.parents:      # belt and braces against traversal
            raise ValueError("storage key escapes the storage root")
        return p

    def put(self, key: str, fileobj: BinaryIO) -> int:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise FileExistsError("storage keys are write-once")
        fileobj.seek(0)
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".part-")
        try:
            with os.fdopen(fd, "wb") as out:
                n = shutil.copyfileobj(fileobj, out) or 0
                out.flush()
                os.fsync(out.fileno())
            os.chmod(tmp, 0o640)
            os.replace(tmp, dest)           # atomic; never leaves a half-written evidence file
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return dest.stat().st_size

    def open(self, key: str) -> BinaryIO:
        return open(self._path(key), "rb")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def purge_all(self) -> int:
        """DEMO RESET ONLY (called by `seed --reset`). Never exposed through the API."""
        n = sum(1 for p in self.root.rglob("*") if p.is_file())
        for child in self.root.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        return n


BACKENDS = {"local": lambda: LocalEvidenceStorage(settings.evidence_storage_dir())}
_override: EvidenceStorage | None = None
_cache: dict[tuple[str, str], EvidenceStorage] = {}


def get_storage() -> EvidenceStorage:
    if _override is not None:
        return _override
    backend = settings.evidence_storage_backend()
    if backend not in BACKENDS:
        raise RuntimeError(f"Unknown EVIDENCE_STORAGE_BACKEND '{backend}'. Known: {sorted(BACKENDS)}")
    key = (backend, settings.evidence_storage_dir())
    if key not in _cache:
        _cache[key] = BACKENDS[backend]()
    return _cache[key]


def set_storage(storage: EvidenceStorage | None) -> None:
    """Swap the backend (tests, or wiring a production backend)."""
    global _override
    _override = storage
