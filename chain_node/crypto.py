"""Hashing and canonical serialisation shared by every part of the chain."""

import hashlib
import json
import re

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj) -> bytes:
    """Serialise to bytes the same way on every node.

    Sorted keys and fixed separators mean two nodes always hash identical
    bytes for identical data, whatever order the keys arrived in.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def is_hex64(value) -> bool:
    return isinstance(value, str) and bool(HEX64.match(value))
