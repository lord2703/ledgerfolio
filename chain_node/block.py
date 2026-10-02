"""Blocks and proof-of-work.

A block's hash covers its header: index, timestamp, previous hash, Merkle root,
difficulty and nonce. The transactions are bound to the header through the
Merkle root, and each block is bound to the one before it through
`previous_hash`, so editing anything anywhere changes every later hash.

Difficulty is the number of leading zero *bits* the block hash must have.
Each extra bit doubles the expected mining work.
"""

import time
from dataclasses import dataclass, field

from .crypto import is_hex64, sha256_hex
from .merkle import EMPTY_ROOT, merkle_root
from .transaction import Transaction, TransactionError

MAX_DIFFICULTY = 255
# 2026-01-01T00:00:00Z. Fixed so every node builds the same genesis block.
GENESIS_TIMESTAMP = 1767225600000


class BlockError(ValueError):
    """Raised with a human-readable reason when a block is invalid."""


def now_ms() -> int:
    return int(time.time() * 1000)


def meets_target(hash_hex: str, difficulty: int) -> bool:
    return int(hash_hex, 16) < (1 << (256 - difficulty))


def header_bytes(index, timestamp, previous_hash, merkle_root_hex, difficulty, nonce) -> bytes:
    return f"{index}|{timestamp}|{previous_hash}|{merkle_root_hex}|{difficulty}|{nonce}".encode(
        "ascii"
    )


@dataclass
class Block:
    index: int
    timestamp: int
    previous_hash: str
    merkle_root: str
    nonce: int
    difficulty: int
    transactions: list = field(default_factory=list)
    hash: str = ""

    def compute_hash(self) -> str:
        return sha256_hex(
            header_bytes(
                self.index,
                self.timestamp,
                self.previous_hash,
                self.merkle_root,
                self.difficulty,
                self.nonce,
            )
        )

    def compute_merkle_root(self) -> str:
        return merkle_root(tx.tx_id for tx in self.transactions)

    @property
    def work(self) -> int:
        """Expected number of hashes needed to mine a block at this difficulty."""
        return 1 << self.difficulty

    # --- serialisation -------------------------------------------------

    def header(self) -> dict:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "merkle_root": self.merkle_root,
            "nonce": self.nonce,
            "difficulty": self.difficulty,
            "hash": self.hash,
            "tx_count": len(self.transactions),
        }

    def to_dict(self) -> dict:
        data = self.header()
        del data["tx_count"]
        data["transactions"] = [tx.to_dict() for tx in self.transactions]
        return data

    @classmethod
    def from_dict(cls, data) -> "Block":
        if not isinstance(data, dict):
            raise BlockError("block must be a JSON object")
        try:
            transactions = [Transaction.from_dict(tx) for tx in data["transactions"]]
            block = cls(
                index=data["index"],
                timestamp=data["timestamp"],
                previous_hash=data["previous_hash"],
                merkle_root=data["merkle_root"],
                nonce=data["nonce"],
                difficulty=data["difficulty"],
                transactions=transactions,
                hash=data["hash"],
            )
        except KeyError as exc:
            raise BlockError(f"block is missing field {exc}") from exc
        except (TypeError, TransactionError) as exc:
            raise BlockError(f"block has malformed transactions: {exc}") from exc
        block.check_format()
        return block

    def check_format(self) -> None:
        for name in ("index", "timestamp", "nonce", "difficulty"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise BlockError(f"block {name} must be a non-negative integer")
        if self.difficulty > MAX_DIFFICULTY:
            raise BlockError("block difficulty is out of range")
        for name in ("previous_hash", "merkle_root", "hash"):
            if not is_hex64(getattr(self, name)):
                raise BlockError(f"block {name} must be a SHA-256 hex digest")


def genesis_block(network: str, min_difficulty: int) -> Block:
    """The fixed first block. Every node on the same network derives the same one."""
    block = Block(
        index=0,
        timestamp=GENESIS_TIMESTAMP,
        previous_hash=sha256_hex(f"ledgerfolio:{network}".encode("utf-8")),
        merkle_root=EMPTY_ROOT,
        nonce=0,
        difficulty=min_difficulty,
        transactions=[],
    )
    block.hash = block.compute_hash()
    return block


def mine_block(
    index: int,
    previous_hash: str,
    transactions,
    difficulty: int,
    timestamp: int | None = None,
    should_stop=None,
) -> Block | None:
    """Proof-of-work: try nonces until the header hash meets the difficulty.

    `should_stop` is an optional callable checked periodically so a miner can
    abandon the search when another node finds the block first. Returns None
    if stopped.
    """
    transactions = list(transactions)
    timestamp = now_ms() if timestamp is None else timestamp
    root = merkle_root(tx.tx_id for tx in transactions)
    target = 1 << (256 - difficulty)
    prefix = f"{index}|{timestamp}|{previous_hash}|{root}|{difficulty}|"
    nonce = 0
    while True:
        digest = sha256_hex(f"{prefix}{nonce}".encode("ascii"))
        if int(digest, 16) < target:
            return Block(
                index=index,
                timestamp=timestamp,
                previous_hash=previous_hash,
                merkle_root=root,
                nonce=nonce,
                difficulty=difficulty,
                transactions=transactions,
                hash=digest,
            )
        nonce += 1
        if should_stop is not None and nonce % 20000 == 0 and should_stop():
            return None
