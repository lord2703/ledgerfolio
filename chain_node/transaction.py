"""Signed transactions.

A transaction says "the holder of this key vouches for this hash at this time".
For Ledgerfolio the payload is the SHA-256 of a receipt's data fields, signed by
the issuer wallet. Only hashes are ever allowed in a payload, so no client name,
price or payment detail can end up on the chain by mistake.
"""

import time
from dataclasses import dataclass

from .crypto import canonical_json, is_hex64, sha256_hex
from .wallet import Wallet, is_valid_public_key, verify_signature

MAX_TYPE_LENGTH = 32
PAYLOAD_KEYS = {"type", "data_hash"}


class TransactionError(ValueError):
    """Raised with a human-readable reason when a transaction is invalid."""


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class Transaction:
    sender: str  # compressed secp256k1 public key, hex
    payload: dict  # {"type": "receipt", "data_hash": <64 hex chars>}
    timestamp: int  # milliseconds since the Unix epoch
    signature: str = ""  # DER-encoded ECDSA signature, hex
    tx_id: str = ""  # SHA-256 of the signed content

    # --- hashing and signing -------------------------------------------

    def signing_bytes(self) -> bytes:
        """The exact bytes that are signed and hashed into the tx id."""
        return canonical_json(
            {"sender": self.sender, "payload": self.payload, "timestamp": self.timestamp}
        )

    def compute_id(self) -> str:
        return sha256_hex(self.signing_bytes())

    @classmethod
    def create(cls, wallet: Wallet, payload: dict, timestamp: int | None = None) -> "Transaction":
        unsigned = cls(
            sender=wallet.public_key_hex,
            payload=dict(payload),
            timestamp=now_ms() if timestamp is None else timestamp,
        )
        return cls(
            sender=unsigned.sender,
            payload=unsigned.payload,
            timestamp=unsigned.timestamp,
            signature=wallet.sign(unsigned.signing_bytes()),
            tx_id=unsigned.compute_id(),
        )

    # --- validation ----------------------------------------------------

    def validate(self) -> None:
        """Check format, id and signature. Raises TransactionError if invalid."""
        if not isinstance(self.sender, str) or not is_valid_public_key(self.sender):
            raise TransactionError("sender is not a valid secp256k1 public key")

        if not isinstance(self.payload, dict) or set(self.payload) != PAYLOAD_KEYS:
            raise TransactionError("payload must contain exactly 'type' and 'data_hash'")
        tx_type = self.payload["type"]
        if not isinstance(tx_type, str) or not 0 < len(tx_type) <= MAX_TYPE_LENGTH:
            raise TransactionError("payload type must be a short non-empty string")
        if not is_hex64(self.payload["data_hash"]):
            raise TransactionError("payload data_hash must be a SHA-256 hex digest")

        if isinstance(self.timestamp, bool) or not isinstance(self.timestamp, int):
            raise TransactionError("timestamp must be an integer (milliseconds)")
        if self.timestamp <= 0:
            raise TransactionError("timestamp must be positive")

        if not is_hex64(self.tx_id) or self.tx_id != self.compute_id():
            raise TransactionError("transaction id does not match its content")
        if not isinstance(self.signature, str) or not verify_signature(
            self.sender, self.signing_bytes(), self.signature
        ):
            raise TransactionError("signature is not valid for this sender and content")

    def is_valid(self) -> bool:
        try:
            self.validate()
        except TransactionError:
            return False
        return True

    # --- serialisation -------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "tx_id": self.tx_id,
            "sender": self.sender,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data) -> "Transaction":
        if not isinstance(data, dict):
            raise TransactionError("transaction must be a JSON object")
        try:
            return cls(
                sender=data["sender"],
                payload=data["payload"],
                timestamp=data["timestamp"],
                signature=data["signature"],
                tx_id=data["tx_id"],
            )
        except KeyError as exc:
            raise TransactionError(f"transaction is missing field {exc}") from exc
