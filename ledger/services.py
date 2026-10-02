"""Receipt hashing, anchoring on the blockchain, and verification.

Only a SHA-256 hash of the receipt's data fields is sent to the chain. Client
names, prices and payment details never leave MySQL.
"""

import datetime
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from chain_node.block import header_bytes, meets_target
from chain_node.crypto import canonical_json, sha256_hex
from chain_node.merkle import verify_proof
from chain_node.transaction import Transaction, TransactionError
from chain_node.wallet import Wallet, WalletError

from .client import NodeClient, NodeRejected, NodeUnavailable

logger = logging.getLogger(__name__)

HASH_VERSION = 1


class LedgerError(Exception):
    """Anchoring could not be done; the message is safe to show to the admin."""


# ----------------------------------------------------------------------
# Hashing
# ----------------------------------------------------------------------

def receipt_data(receipt) -> dict:
    """The receipt's data fields in a fixed, canonical form."""
    return {
        "v": HASH_VERSION,
        "document_type": receipt.document_type,
        "receipt_number": receipt.receipt_number,
        "issued_at": receipt.issued_at.astimezone(datetime.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "client_name": receipt.client_name,
        "system_name": receipt.system_name,
        "amount": f"{Decimal(receipt.amount):.2f}",
        "balance_after": f"{Decimal(receipt.balance_after):.2f}",
        "payment_method": receipt.payment_method,
        "payment_date": receipt.payment_date.isoformat(),
        "salt": receipt.salt,
    }


def receipt_hash(receipt) -> str:
    """SHA-256 over the data fields (not the PDF), so PDFs can be regenerated."""
    return sha256_hex(canonical_json(receipt_data(receipt)))


# ----------------------------------------------------------------------
# Issuer wallet
# ----------------------------------------------------------------------

_wallet_cache = {}


def issuer_wallet() -> Wallet:
    """The wallet that signs receipts, loaded from the environment or a key file."""
    source = (settings.ISSUER_PRIVATE_KEY, settings.ISSUER_KEY_FILE)
    if source in _wallet_cache:
        return _wallet_cache[source]
    private_hex, key_file = source
    try:
        if private_hex:
            wallet = Wallet.from_private_hex(private_hex)
        elif key_file:
            wallet = Wallet.from_pem(Path(key_file).read_bytes())
        else:
            raise LedgerError(
                "No issuer key is configured. Run `python manage.py generate_issuer_key` "
                "and set ISSUER_KEY_FILE in .env."
            )
    except OSError as exc:
        raise LedgerError(f"The issuer key file could not be read: {key_file}") from exc
    except WalletError as exc:
        raise LedgerError(f"The issuer key is not usable: {exc}") from exc
    _wallet_cache.clear()
    _wallet_cache[source] = wallet
    return wallet


def issuer_public_key() -> str:
    return issuer_wallet().public_key_hex


# ----------------------------------------------------------------------
# Anchoring
# ----------------------------------------------------------------------

def anchor(receipt, client: NodeClient | None = None):
    """Record the receipt's hash on the chain as a signed transaction.

    Safe to call again: an already anchored receipt re-sends the same signed
    transaction (in case the node lost it) and refreshes its status.
    """
    client = client or NodeClient()
    data_hash = receipt_hash(receipt)

    if receipt.signed_tx:
        if data_hash != receipt.content_hash:
            raise LedgerError(
                f"{receipt.receipt_number} was changed after it was anchored, so it cannot be "
                "anchored again. Delete it and issue a new receipt instead."
            )
        tx_data = receipt.signed_tx
    else:
        tx = Transaction.create(
            issuer_wallet(), {"type": receipt.document_type, "data_hash": data_hash}
        )
        tx_data = tx.to_dict()

    try:
        client.submit_transaction(tx_data)
    except NodeUnavailable as exc:
        raise LedgerError(f"The blockchain node is not reachable ({exc}).") from exc
    except NodeRejected as exc:
        raise LedgerError(f"The blockchain node rejected the transaction: {exc}") from exc

    receipt.content_hash = data_hash
    receipt.signed_tx = tx_data
    receipt.tx_id = tx_data["tx_id"]
    if receipt.ledger_status == receipt.LedgerStatus.UNANCHORED:
        receipt.ledger_status = receipt.LedgerStatus.PENDING
    receipt.save()

    # Ask for a block now. If the node's own miner got there first this simply
    # reports nothing left to mine. A slow or failed mine is not an error: the
    # transaction is safely in the mempool and the status is refreshed later.
    try:
        client.mine(timeout=settings.CHAIN_CONFIRM_TIMEOUT)
    except (NodeUnavailable, NodeRejected) as exc:
        logger.warning("Mining request for %s did not complete: %s", receipt, exc)
    return refresh(receipt, client)


def refresh(receipt, client: NodeClient | None = None):
    """Update the receipt's ledger status and block reference from the node."""
    if not receipt.tx_id:
        return receipt
    client = client or NodeClient()
    try:
        info = client.get_transaction(receipt.tx_id)
    except (NodeUnavailable, NodeRejected):
        return receipt
    if info and info["status"] == "confirmed":
        block = info["block"]
        changed = (
            receipt.ledger_status != receipt.LedgerStatus.CONFIRMED
            or receipt.block_index != block["index"]
            or receipt.block_hash != block["hash"]
        )
        if changed:
            receipt.ledger_status = receipt.LedgerStatus.CONFIRMED
            receipt.block_index = block["index"]
            receipt.block_hash = block["hash"]
            receipt.save(update_fields=["ledger_status", "block_index", "block_hash"])
    return receipt


# ----------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------

VALID, PENDING, TAMPERED, UNAVAILABLE = "valid", "pending", "tampered", "unavailable"


@dataclass
class Check:
    key: str
    label: str
    passed: bool | None = None  # None = could not be checked
    detail: str = ""


@dataclass
class Verification:
    state: str
    summary: str
    checks: list = field(default_factory=list)
    data_hash: str = ""
    tx_id: str = ""
    block: dict | None = None
    confirmations: int = 0

    @property
    def is_valid(self) -> bool:
        return self.state == VALID


def verify(receipt, client: NodeClient | None = None) -> Verification:
    """Independently re-check a receipt against the blockchain.

    Django recomputes the data hash from MySQL and re-verifies the signature,
    the Merkle proof and the block's proof-of-work itself, instead of trusting
    a yes/no from the node.
    """
    client = client or NodeClient()
    data_hash = receipt_hash(receipt)
    checks = {
        "data": Check("data", "Receipt data matches its recorded fingerprint"),
        "ledger": Check("ledger", "Fingerprint is recorded on the blockchain"),
        "signature": Check("signature", "Transaction is signed by the issuer"),
        "block": Check("block", "Transaction is sealed in a mined block"),
        "chain": Check("chain", "The whole chain passes validation"),
    }
    result = Verification(
        state=TAMPERED, summary="", checks=list(checks.values()),
        data_hash=data_hash, tx_id=receipt.tx_id,
    )

    def finish(state, summary):
        result.state, result.summary = state, summary
        return result

    # 1. Data in MySQL against the fingerprint stored when it was issued.
    data_check = checks["data"]
    if not receipt.content_hash:
        data_check.detail = "This receipt has not been fingerprinted yet."
    else:
        data_check.passed = data_hash == receipt.content_hash
        data_check.detail = (
            "The data hashes to the same SHA-256 value as when it was issued."
            if data_check.passed
            else "The receipt's data no longer matches the fingerprint taken when it was issued."
        )
    if data_check.passed is False:
        return finish(TAMPERED, "This receipt's data was changed after it was issued.")

    if not receipt.tx_id:
        checks["ledger"].detail = "It has not been sent to the blockchain yet."
        return finish(PENDING, "This receipt has not been recorded on the blockchain yet.")

    # 2. The transaction on the node.
    try:
        info = client.get_transaction(receipt.tx_id)
        validation = client.validate()
        expected_signer = issuer_public_key()
    except (NodeUnavailable, NodeRejected, LedgerError) as exc:
        logger.warning("Verification of %s could not reach the ledger: %s", receipt, exc)
        return finish(
            UNAVAILABLE,
            "The blockchain node cannot be reached right now, so this receipt "
            "cannot be checked. Please try again shortly.",
        )

    ledger_check = checks["ledger"]
    if info is None:
        ledger_check.passed = False
        ledger_check.detail = "The blockchain has no transaction for this receipt."
        return finish(TAMPERED, "This receipt's transaction is missing from the blockchain.")

    tx_data = info["transaction"]
    payload = tx_data.get("payload") if isinstance(tx_data, dict) else None
    on_chain_hash = payload.get("data_hash") if isinstance(payload, dict) else None
    ledger_check.passed = on_chain_hash == data_hash and tx_data.get("tx_id") == receipt.tx_id
    ledger_check.detail = (
        "The hash on the blockchain equals the hash of this receipt's data."
        if ledger_check.passed
        else "The hash on the blockchain is different from this receipt's data."
    )

    # 3. Signature, and that it is the issuer's.
    signature_check = checks["signature"]
    try:
        tx = Transaction.from_dict(tx_data)
        tx.validate()
    except TransactionError as exc:
        signature_check.passed = False
        signature_check.detail = f"The transaction is not valid: {exc}."
    else:
        signature_check.passed = tx.sender == expected_signer
        signature_check.detail = (
            "The ECDSA signature is valid and belongs to the issuer's wallet."
            if signature_check.passed
            else "The transaction was signed by a key that is not the issuer's."
        )

    # 4. Block inclusion: Merkle proof and proof-of-work.
    block_check = checks["block"]
    pending = info["status"] != "confirmed"
    if pending:
        block_check.detail = "The transaction is waiting in the mempool to be mined."
    else:
        block = info["block"]
        result.block = block
        result.confirmations = info.get("confirmations", 0)
        try:
            recomputed = sha256_hex(
                header_bytes(
                    block["index"], block["timestamp"], block["previous_hash"],
                    block["merkle_root"], block["difficulty"], block["nonce"],
                )
            )
            block_check.passed = (
                verify_proof(receipt.tx_id, info["proof"], block["merkle_root"])
                and recomputed == block["hash"]
                and meets_target(block["hash"], block["difficulty"])
            )
        except (KeyError, TypeError, ValueError):
            block_check.passed = False
        block_check.detail = (
            f"The Merkle proof leads to the root of block #{block.get('index')}, "
            "and the block's hash meets its proof-of-work."
            if block_check.passed
            else "The Merkle proof or the block's proof-of-work does not check out."
        )

    # 5. Whole-chain validity, as reported by the node's full re-validation.
    chain_check = checks["chain"]
    chain_check.passed = bool(validation.get("valid"))
    chain_check.detail = (
        f"All {validation.get('height', 0) + 1} blocks link back to the genesis block."
        if chain_check.passed
        else f"The chain failed validation: {validation.get('reason')}."
    )

    failed = [check for check in result.checks if check.passed is False]
    if failed:
        reasons = {
            "ledger": "The record on the blockchain does not match this receipt.",
            "signature": "The blockchain record was not signed by the issuer.",
            "block": "The blockchain record could not be proven to be in its block.",
            "chain": "The blockchain itself failed validation.",
        }
        return finish(TAMPERED, reasons[failed[0].key])
    if pending:
        return finish(
            PENDING,
            "This receipt is signed and waiting to be sealed into a block. Check back in a moment.",
        )
    return finish(
        VALID,
        "Nothing in it has changed since it was issued, and its fingerprint is sealed in "
        f"block #{result.block['index']} of the ledger.",
    )


# ----------------------------------------------------------------------
# Chain overview for the public ledger page and the admin dashboard
# ----------------------------------------------------------------------

def overview(client: NodeClient | None = None, blocks: int = 8) -> dict:
    """Node status, chain validity and latest block headers; marks the node offline on failure."""
    client = client or NodeClient()
    try:
        status = client.status()
        validation = client.validate()
        latest = client.latest_blocks(blocks)
    except (NodeUnavailable, NodeRejected):
        return {"online": False}
    for block in latest:
        block["time"] = datetime.datetime.fromtimestamp(
            block["timestamp"] / 1000, tz=datetime.timezone.utc
        )
    return {
        "online": True,
        "status": status,
        "valid": validation.get("valid", False),
        "reason": validation.get("reason"),
        "blocks": latest,
    }
