"""A running node: chain + mempool + miner + peer-to-peer networking.

The node never trusts its peers. Transactions and blocks that arrive over the
network go through the same validation as local ones, and a peer's chain only
replaces ours after being re-validated from genesis and shown to carry more
accumulated proof-of-work.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from .block import Block, BlockError, mine_block, now_ms
from .chain import MAX_BLOCK_TRANSACTIONS, Blockchain, ChainError
from .config import NodeConfig, normalize_url
from .mempool import Mempool
from .storage import Storage
from .transaction import Transaction, TransactionError

logger = logging.getLogger("chain_node")

ORIGIN_HEADER = "X-Node-Url"
VALIDATION_CACHE_SECONDS = 10


class NodeError(Exception):
    """A request the node understood but refuses. Carries an HTTP-ish status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


_http = None


def http_request(method: str, url: str, json=None, headers=None, timeout: float = 5.0):
    """Talk to a peer over one shared connection pool."""
    global _http
    if _http is None:
        _http = httpx.Client()
    response = _http.request(method, url, json=json, headers=headers, timeout=timeout)
    return response.status_code, response.json()


class Node:
    def __init__(self, config: NodeConfig, storage=None, http=http_request):
        self.config = config
        self.storage = storage if storage is not None else Storage(config.data_dir)
        self.http = http
        self.lock = threading.RLock()
        self.mempool = Mempool(config.max_mempool)
        self.peers = []
        # Set when the chain file on disk fails validation at startup.
        self.corrupt_reason = None

        self._mining_lock = threading.Lock()
        self._wake_miner = threading.Event()
        self._stopping = threading.Event()
        self._threads = []
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="p2p")
        self._validation_cache = None  # (tip hash, checked at, valid, reason)

        self._load()

    # ------------------------------------------------------------------
    # Startup and persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        network, min_difficulty = self.config.network, self.config.min_difficulty
        stored = self.storage.load("chain")
        if stored is None:
            self.chain = Blockchain(network, min_difficulty)
            self._save_chain()
        else:
            try:
                blocks = [Block.from_dict(item) for item in stored["blocks"]]
                self.chain = Blockchain(network, min_difficulty, blocks)
            except (ChainError, BlockError, KeyError, TypeError) as exc:
                # Keep the node up so it can report the fault and heal from a
                # peer, but stop it from building on a chain it cannot trust.
                self.corrupt_reason = str(exc)
                self.chain = Blockchain(network, min_difficulty)
                logger.critical("Stored chain failed validation: %s", exc)

        for item in self.storage.load("mempool", []):
            try:
                self._accept_transaction(Transaction.from_dict(item))
            except (TransactionError, NodeError):
                continue

        for peer in list(self.storage.load("peers", [])) + list(self.config.peers):
            self._remember_peer(peer)

    def _save_chain(self) -> None:
        self.storage.save(
            "chain",
            {
                "network": self.chain.network,
                "min_difficulty": self.chain.min_difficulty,
                "blocks": self.chain.to_list(),
            },
        )

    def _save_mempool(self) -> None:
        self.storage.save("mempool", self.mempool.to_list())

    def start(self) -> None:
        """Start the background miner and peer sync loops."""
        self._stopping.clear()
        for target in (self._miner_loop, self._sync_loop):
            thread = threading.Thread(target=target, daemon=True, name=target.__name__)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stopping.set()
        self._wake_miner.set()
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads.clear()
        self._pool.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    def _accept_transaction(self, tx: Transaction) -> bool:
        """Validate and queue a transaction. Returns False if already known."""
        tx.validate()
        with self.lock:
            if self.chain.has_transaction(tx.tx_id) or tx.tx_id in self.mempool:
                return False
            allowed = self.config.allowed_senders
            if allowed and tx.sender not in allowed:
                raise NodeError("this node does not accept transactions from that sender", 403)
            if self.mempool.is_full():
                raise NodeError("mempool is full, try again later", 503)
            self.mempool.add(tx)
            return True

    def submit_transaction(self, data, origin=None):
        """Accept a signed transaction from a client or a peer.

        Returns (transaction, is_new). Raises TransactionError if invalid.
        """
        self._require_healthy()
        tx = Transaction.from_dict(data)
        is_new = self._accept_transaction(tx)
        if is_new:
            with self.lock:
                self._save_mempool()
            self._broadcast("/transactions", tx.to_dict(), exclude=origin)
            self._wake_miner.set()
        return tx, is_new

    def transaction_info(self, tx_id: str):
        """Everything a verifier needs about one transaction, or None."""
        with self.lock:
            pending = self.mempool.get(tx_id)
            if pending is not None:
                return {"status": "pending", "transaction": pending.to_dict()}
            found = self.chain.find_transaction(tx_id)
            if found is None:
                return None
            block, position = found
            return {
                "status": "confirmed",
                "transaction": block.transactions[position].to_dict(),
                "block": block.header(),
                "position": position,
                "proof": self.chain.proof_for(tx_id),
                "confirmations": self.chain.height - block.index + 1,
            }

    # ------------------------------------------------------------------
    # Mining
    # ------------------------------------------------------------------

    def mine(self, allow_empty: bool = False):
        """Mine one block from the mempool. Returns the block, or None."""
        self._require_healthy()
        with self._mining_lock:
            with self.lock:
                transactions = self.mempool.take(MAX_BLOCK_TRANSACTIONS)
                previous = self.chain.tip
            if not transactions and not allow_empty:
                return None

            block = mine_block(
                index=previous.index + 1,
                previous_hash=previous.hash,
                transactions=transactions,
                difficulty=self.config.difficulty,
                timestamp=max(now_ms(), previous.timestamp),
                should_stop=lambda: self.chain.tip is not previous or self._stopping.is_set(),
            )
            if block is None:
                return None

            with self.lock:
                if self.chain.tip is not previous:
                    return None  # someone else extended the chain first
                self.chain.add_block(block)
                self.mempool.remove(tx.tx_id for tx in block.transactions)
                self._save_chain()
                self._save_mempool()
            logger.info("Mined block %s with %s tx", block.index, len(block.transactions))

        self._broadcast("/blocks", block.to_dict())
        return block

    def _miner_loop(self) -> None:
        while not self._stopping.is_set():
            self._wake_miner.wait(timeout=5)
            self._wake_miner.clear()
            if self._stopping.is_set() or not self.config.auto_mine:
                continue
            try:
                while len(self.mempool) and not self._stopping.is_set():
                    if self.mine() is None:
                        break
            except (NodeError, ChainError) as exc:
                logger.warning("Mining skipped: %s", exc)
            except Exception:
                logger.exception("Unexpected error while mining")

    # ------------------------------------------------------------------
    # Blocks from peers and fork resolution
    # ------------------------------------------------------------------

    def receive_block(self, data, origin=None) -> str:
        """Handle a block broadcast by a peer.

        Returns "accepted", "known" or "synced"/"ignored" when the block did
        not extend our tip and we compared whole chains instead. Raises
        ChainError or BlockError if the block is invalid.
        """
        block = Block.from_dict(data)
        with self.lock:
            if block.index <= self.chain.height and self.chain.blocks[block.index].hash == block.hash:
                return "known"
            extends_tip = block.previous_hash == self.chain.tip.hash and not self.corrupt_reason
            if extends_tip:
                self.chain.add_block(block)
                self.mempool.remove(tx.tx_id for tx in block.transactions)
                self._save_chain()
                self._save_mempool()
        if extends_tip:
            logger.info("Accepted block %s from %s", block.index, origin or "peer")
            self._broadcast("/blocks", block.to_dict(), exclude=origin)
            return "accepted"

        # The block is on a different branch, or ahead of us. Decide by
        # comparing accumulated work across whole chains.
        peers = [origin] if origin else None
        return "synced" if self.sync(peers) else "ignored"

    def sync(self, peers=None) -> bool:
        """Adopt the valid chain with the most accumulated work among peers."""
        adopted = False
        for peer in peers or list(self.peers):
            try:
                adopted = self._sync_from(peer) or adopted
            except Exception as exc:  # a bad or offline peer must never crash us
                logger.debug("Sync with %s failed: %s", peer, exc)
        return adopted

    def _sync_from(self, peer: str) -> bool:
        status, info = self.http("GET", f"{peer}/status", headers=self._headers())
        if status != 200 or info.get("genesis_hash") != self.chain.blocks[0].hash:
            return False
        if not self.corrupt_reason and int(info["total_work"]) <= self.chain.total_work:
            return False

        status, payload = self.http("GET", f"{peer}/chain", headers=self._headers(), timeout=30.0)
        if status != 200:
            return False
        candidate = [Block.from_dict(item) for item in payload["blocks"]]

        with self.lock:
            if self.corrupt_reason:
                # Our stored chain is untrustworthy, so any valid chain wins.
                orphaned = []
                self.chain = Blockchain(self.config.network, self.config.min_difficulty, candidate)
                self.corrupt_reason = None
            else:
                orphaned = self.chain.replace_chain(candidate)
                if orphaned is None:
                    return False
            self._validation_cache = None
            self.mempool.remove(self.chain.transaction_ids())
            for tx in orphaned:
                try:
                    self._accept_transaction(tx)
                except (TransactionError, NodeError):
                    continue
            self._save_chain()
            self._save_mempool()
        logger.info("Adopted chain from %s (height %s)", peer, self.chain.height)
        if len(self.mempool):
            self._wake_miner.set()
        return True

    def _sync_loop(self) -> None:
        self.announce()
        self.sync()
        while not self._stopping.wait(timeout=self.config.sync_interval):
            self.sync()

    # ------------------------------------------------------------------
    # Peers
    # ------------------------------------------------------------------

    def _remember_peer(self, url) -> bool:
        if not isinstance(url, str):
            return False
        url = normalize_url(url)
        if not url.startswith(("http://", "https://")) or url == self.config.public_url:
            return False
        with self.lock:
            if url in self.peers:
                return False
            self.peers.append(url)
        return True

    def add_peer(self, url) -> bool:
        added = self._remember_peer(url)
        if added:
            with self.lock:
                self.storage.save("peers", self.peers)
        return added

    def announce(self) -> None:
        """Tell every known peer how to reach us, so the link works both ways."""
        for peer in list(self.peers):
            try:
                self.http(
                    "POST", f"{peer}/peers", json={"url": self.config.public_url},
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.debug("Could not announce to %s: %s", peer, exc)

    def _headers(self) -> dict:
        return {ORIGIN_HEADER: self.config.public_url}

    def _broadcast(self, path: str, payload, exclude=None) -> None:
        targets = [peer for peer in list(self.peers) if peer != exclude]
        for peer in targets:
            if self.config.synchronous_broadcast:
                self._send(peer, path, payload)
            else:
                self._pool.submit(self._send, peer, path, payload)

    def _send(self, peer: str, path: str, payload) -> None:
        try:
            self.http("POST", f"{peer}{path}", json=payload, headers=self._headers())
        except Exception as exc:
            logger.debug("Broadcast to %s failed: %s", peer, exc)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def _require_healthy(self) -> None:
        if self.corrupt_reason:
            raise NodeError(
                f"this node's stored chain failed validation ({self.corrupt_reason}); "
                "restore it from a backup or let it sync from a healthy peer",
                503,
            )

    def validate(self, fresh: bool = False):
        """Re-validate the whole chain from genesis. Returns (valid, reason)."""
        if self.corrupt_reason:
            return False, self.corrupt_reason
        with self.lock:
            tip_hash = self.chain.tip.hash
            cache = self._validation_cache
            if (
                not fresh
                and cache
                and cache[0] == tip_hash
                and time.monotonic() - cache[1] < VALIDATION_CACHE_SECONDS
            ):
                return cache[2], cache[3]
            valid, reason = self.chain.check()
            self._validation_cache = (tip_hash, time.monotonic(), valid, reason)
            return valid, reason

    def status(self) -> dict:
        with self.lock:
            tip = self.chain.tip
            return {
                "network": self.chain.network,
                "node_url": self.config.public_url,
                "height": self.chain.height,
                "tip_hash": tip.hash,
                "tip_timestamp": tip.timestamp,
                "genesis_hash": self.chain.blocks[0].hash,
                "min_difficulty": self.chain.min_difficulty,
                "mining_difficulty": self.config.difficulty,
                # Sent as a string: accumulated work can outgrow a JSON number.
                "total_work": str(self.chain.total_work),
                "transactions": self.chain.transaction_count,
                "mempool": len(self.mempool),
                "peers": len(self.peers),
                "auto_mine": self.config.auto_mine,
                "healthy": self.corrupt_reason is None,
            }
