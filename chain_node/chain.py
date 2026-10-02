"""The blockchain: an ordered list of validated blocks plus the consensus rules.

Every node runs these same rules independently. Nothing is trusted because a
peer said so: blocks and transactions are re-checked on arrival, and a whole
chain is re-checked from the genesis block before it can replace ours.
"""

from .block import Block, BlockError, genesis_block, meets_target, now_ms
from .merkle import merkle_proof
from .transaction import TransactionError

MAX_BLOCK_TRANSACTIONS = 500
MAX_FUTURE_DRIFT_MS = 2 * 60 * 60 * 1000


class ChainError(ValueError):
    """Raised with a human-readable reason when a block or chain is invalid."""


def validate_block(block: Block, previous: Block, min_difficulty: int, seen_tx_ids, now=None):
    """Check one block against the block before it.

    `seen_tx_ids` holds every transaction id already confirmed earlier in the
    chain. Returns the set of transaction ids in this block.
    """
    try:
        block.check_format()
    except BlockError as exc:
        raise ChainError(str(exc)) from exc

    where = f"block {block.index}"
    if block.index != previous.index + 1:
        raise ChainError(f"{where}: index does not follow block {previous.index}")
    if block.previous_hash != previous.hash:
        raise ChainError(f"{where}: previous hash does not match block {previous.index}")
    if block.timestamp < previous.timestamp:
        raise ChainError(f"{where}: timestamp is earlier than the previous block")
    now = now_ms() if now is None else now
    if block.timestamp > now + MAX_FUTURE_DRIFT_MS:
        raise ChainError(f"{where}: timestamp is too far in the future")
    if block.difficulty < min_difficulty:
        raise ChainError(f"{where}: difficulty is below the network minimum")
    if len(block.transactions) > MAX_BLOCK_TRANSACTIONS:
        raise ChainError(f"{where}: too many transactions")
    if block.merkle_root != block.compute_merkle_root():
        raise ChainError(f"{where}: Merkle root does not match its transactions")
    if block.hash != block.compute_hash():
        raise ChainError(f"{where}: stored hash does not match the header")
    if not meets_target(block.hash, block.difficulty):
        raise ChainError(f"{where}: hash does not meet the proof-of-work difficulty")

    tx_ids = set()
    for tx in block.transactions:
        try:
            tx.validate()
        except TransactionError as exc:
            raise ChainError(f"{where}: invalid transaction: {exc}") from exc
        if tx.tx_id in seen_tx_ids or tx.tx_id in tx_ids:
            raise ChainError(f"{where}: duplicate transaction {tx.tx_id[:12]}")
        tx_ids.add(tx.tx_id)
    return tx_ids


def validate_chain(blocks, network: str, min_difficulty: int, now=None) -> None:
    """Re-check an entire chain from genesis. Raises ChainError on any fault."""
    if not blocks:
        raise ChainError("chain is empty")
    if blocks[0].to_dict() != genesis_block(network, min_difficulty).to_dict():
        raise ChainError("genesis block does not match this network")
    seen = set()
    for previous, block in zip(blocks, blocks[1:]):
        seen |= validate_block(block, previous, min_difficulty, seen, now)


def chain_work(blocks) -> int:
    """Accumulated proof-of-work. The genesis block is not mined, so it adds none."""
    return sum(block.work for block in blocks[1:])


class Blockchain:
    def __init__(self, network: str, min_difficulty: int, blocks=None):
        self.network = network
        self.min_difficulty = min_difficulty
        self.blocks = [genesis_block(network, min_difficulty)]
        self._tx_index = {}
        if blocks:
            validate_chain(blocks, network, min_difficulty)
            self._set_blocks(list(blocks))

    def _set_blocks(self, blocks) -> None:
        self.blocks = blocks
        self._tx_index = {
            tx.tx_id: (block.index, position)
            for block in blocks
            for position, tx in enumerate(block.transactions)
        }

    # --- reading -------------------------------------------------------

    @property
    def tip(self) -> Block:
        return self.blocks[-1]

    @property
    def height(self) -> int:
        return self.tip.index

    @property
    def total_work(self) -> int:
        return chain_work(self.blocks)

    @property
    def transaction_count(self) -> int:
        return len(self._tx_index)

    def transaction_ids(self):
        return list(self._tx_index)

    def has_transaction(self, tx_id: str) -> bool:
        return tx_id in self._tx_index

    def find_transaction(self, tx_id: str):
        """Return (block, position) for a confirmed transaction, or None."""
        location = self._tx_index.get(tx_id)
        if location is None:
            return None
        block_index, position = location
        return self.blocks[block_index], position

    def proof_for(self, tx_id: str):
        """Merkle proof that a confirmed transaction is in its block, or None."""
        found = self.find_transaction(tx_id)
        if found is None:
            return None
        block, position = found
        return merkle_proof([tx.tx_id for tx in block.transactions], position)

    def check(self):
        """Full re-validation of the chain we hold. Returns (valid, reason)."""
        try:
            validate_chain(self.blocks, self.network, self.min_difficulty)
        except ChainError as exc:
            return False, str(exc)
        return True, None

    # --- writing -------------------------------------------------------

    def add_block(self, block: Block) -> None:
        """Append a block to the tip if it passes validation."""
        validate_block(block, self.tip, self.min_difficulty, self._tx_index)
        self.blocks.append(block)
        for position, tx in enumerate(block.transactions):
            self._tx_index[tx.tx_id] = (block.index, position)

    def replace_chain(self, candidate):
        """Fork resolution: adopt `candidate` if it is valid and has more work.

        Returns the transactions that were confirmed on our old chain but are
        not on the new one (so the caller can put them back in the mempool),
        or None if the candidate was not adopted. Raises ChainError if the
        candidate is invalid.
        """
        candidate = list(candidate)
        validate_chain(candidate, self.network, self.min_difficulty)
        if chain_work(candidate) <= self.total_work:
            return None
        old_blocks = self.blocks
        self._set_blocks(candidate)
        return [
            tx
            for block in old_blocks
            for tx in block.transactions
            if tx.tx_id not in self._tx_index
        ]

    def to_list(self):
        return [block.to_dict() for block in self.blocks]
