"""Merkle tree over a block's transaction ids.

The root goes in the block header, so changing, adding, removing or reordering
any transaction changes the header hash. A Merkle proof lets someone holding
only one transaction and the block header confirm the transaction is in the
block, without downloading the others.

Leaves and inner nodes are hashed with different prefixes so an inner node can
never be passed off as a leaf (second-preimage protection). An odd level
duplicates its last node, as Bitcoin does; the chain rejects duplicate
transactions, so that duplication cannot be abused to forge a second tx list
with the same root.
"""

from .crypto import sha256_hex

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"
EMPTY_ROOT = sha256_hex(b"")


def leaf_hash(tx_id: str) -> str:
    return sha256_hex(LEAF_PREFIX + bytes.fromhex(tx_id))


def node_hash(left: str, right: str) -> str:
    return sha256_hex(NODE_PREFIX + bytes.fromhex(left) + bytes.fromhex(right))


def _levels(tx_ids):
    """All levels of the tree, leaves first, root level last."""
    level = [leaf_hash(tx_id) for tx_id in tx_ids]
    levels = [level]
    while len(level) > 1:
        if len(level) % 2:
            level = level + [level[-1]]
        level = [node_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        levels.append(level)
    return levels


def merkle_root(tx_ids) -> str:
    tx_ids = list(tx_ids)
    if not tx_ids:
        return EMPTY_ROOT
    return _levels(tx_ids)[-1][0]


def merkle_proof(tx_ids, index: int):
    """Sibling hashes needed to rebuild the root from the leaf at `index`.

    Each step is {"hash": sibling, "position": "left" | "right"}, where
    position says which side the sibling sits on.
    """
    tx_ids = list(tx_ids)
    if not 0 <= index < len(tx_ids):
        raise IndexError("transaction index out of range")
    proof = []
    for level in _levels(tx_ids)[:-1]:
        if len(level) % 2:
            level = level + [level[-1]]
        sibling = index ^ 1
        proof.append(
            {"hash": level[sibling], "position": "left" if sibling < index else "right"}
        )
        index //= 2
    return proof


def verify_proof(tx_id: str, proof, root: str) -> bool:
    try:
        current = leaf_hash(tx_id)
        for step in proof:
            if step["position"] == "left":
                current = node_hash(step["hash"], current)
            elif step["position"] == "right":
                current = node_hash(current, step["hash"])
            else:
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return current == root
