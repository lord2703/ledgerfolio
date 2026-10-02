"""Shared builders for the chain tests. Difficulty is kept tiny so mining is instant."""

from chain_node.block import mine_block
from chain_node.chain import Blockchain
from chain_node.crypto import sha256_hex
from chain_node.transaction import Transaction
from chain_node.wallet import Wallet

NETWORK = "test-net"
DIFFICULTY = 8


def receipt_tx(wallet: Wallet, label: str, timestamp: int | None = None) -> Transaction:
    payload = {"type": "receipt", "data_hash": sha256_hex(label.encode())}
    return Transaction.create(wallet, payload, timestamp=timestamp)


def next_block(chain: Blockchain, transactions=(), difficulty: int = DIFFICULTY):
    tip = chain.tip
    return mine_block(tip.index + 1, tip.hash, list(transactions), difficulty)


def build_chain(wallet: Wallet, blocks: int = 3, per_block: int = 2) -> Blockchain:
    chain = Blockchain(NETWORK, DIFFICULTY)
    for b in range(blocks):
        txs = [receipt_tx(wallet, f"receipt-{b}-{i}") for i in range(per_block)]
        chain.add_block(next_block(chain, txs))
    return chain
