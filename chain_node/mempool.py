"""The mempool: valid transactions waiting to be mined into a block."""

from .transaction import Transaction


class Mempool:
    def __init__(self, max_size: int = 5000):
        self.max_size = max_size
        self._pending = {}  # tx_id -> Transaction, in arrival order

    def __len__(self):
        return len(self._pending)

    def __contains__(self, tx_id):
        return tx_id in self._pending

    def get(self, tx_id: str):
        return self._pending.get(tx_id)

    def is_full(self) -> bool:
        return len(self._pending) >= self.max_size

    def add(self, tx: Transaction) -> None:
        self._pending[tx.tx_id] = tx

    def take(self, limit: int):
        """The oldest `limit` transactions, without removing them."""
        return list(self._pending.values())[:limit]

    def remove(self, tx_ids) -> None:
        for tx_id in tx_ids:
            self._pending.pop(tx_id, None)

    def to_list(self):
        return [tx.to_dict() for tx in self._pending.values()]
