"""Wallets: ECDSA key pairs on the secp256k1 curve.

A wallet's public key identifies the sender of a transaction. The private key
signs; anyone can verify with the public key. Private keys are never logged or
included in a repr.
"""

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .crypto import sha256_hex

CURVE = ec.SECP256K1()
_SIGNATURE_ALGORITHM = ec.ECDSA(hashes.SHA256())


class WalletError(ValueError):
    pass


class Wallet:
    def __init__(self, private_key: ec.EllipticCurvePrivateKey):
        if not isinstance(private_key.curve, ec.SECP256K1):
            raise WalletError("wallet keys must be on the secp256k1 curve")
        self._private_key = private_key

    def __repr__(self):
        return f"Wallet(address={self.address})"

    # --- construction -------------------------------------------------

    @classmethod
    def generate(cls) -> "Wallet":
        return cls(ec.generate_private_key(CURVE))

    @classmethod
    def from_private_hex(cls, private_hex: str) -> "Wallet":
        try:
            secret = int(private_hex.strip(), 16)
            return cls(ec.derive_private_key(secret, CURVE))
        except (ValueError, AttributeError) as exc:
            raise WalletError("invalid private key") from exc

    @classmethod
    def from_pem(cls, pem: bytes, password: bytes | None = None) -> "Wallet":
        try:
            key = serialization.load_pem_private_key(pem, password=password)
        except (ValueError, TypeError) as exc:
            raise WalletError("could not read the PEM private key") from exc
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise WalletError("PEM file does not hold an elliptic-curve key")
        return cls(key)

    # --- export -------------------------------------------------------

    def to_pem(self, password: bytes | None = None) -> bytes:
        encryption = (
            serialization.BestAvailableEncryption(password)
            if password
            else serialization.NoEncryption()
        )
        return self._private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            encryption,
        )

    def private_hex(self) -> str:
        """The raw secret. Handle with care: never log or commit it."""
        return format(self._private_key.private_numbers().private_value, "064x")

    @property
    def public_key_hex(self) -> str:
        return self._private_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.CompressedPoint,
        ).hex()

    @property
    def address(self) -> str:
        return address_from_public_key(self.public_key_hex)

    # --- signing ------------------------------------------------------

    def sign(self, message: bytes) -> str:
        return self._private_key.sign(message, _SIGNATURE_ALGORITHM).hex()


def address_from_public_key(public_key_hex: str) -> str:
    """Short, shareable identifier derived from a public key."""
    return sha256_hex(bytes.fromhex(public_key_hex))[:40]


def is_valid_public_key(public_key_hex) -> bool:
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(CURVE, bytes.fromhex(public_key_hex))
    except (ValueError, TypeError):
        return False
    return True


def verify_signature(public_key_hex: str, message: bytes, signature_hex: str) -> bool:
    try:
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(
            CURVE, bytes.fromhex(public_key_hex)
        )
        public_key.verify(bytes.fromhex(signature_hex), message, _SIGNATURE_ALGORITHM)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True
