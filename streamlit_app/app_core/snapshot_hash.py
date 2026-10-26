"""Stable hashes for text snapshot artifacts across operating systems."""

import hashlib
from pathlib import Path


def sha256_file(path: Path, *, normalize_newlines: bool = False) -> str:
    content = path.read_bytes()
    if normalize_newlines:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()
