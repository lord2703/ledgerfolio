"""Ledgerfolio blockchain node.

A small but real blockchain: signed transactions, proof-of-work blocks,
Merkle proofs, a mempool, and peer-to-peer sync over HTTP.

This package is deliberately independent: it must never import Django or any
Tracker code. Django talks to a running node through its HTTP API (see the
`ledger` app), and may reuse the pure helpers here (wallet, transaction,
merkle) so both sides serialise and hash data identically.
"""

__version__ = "1.0.0"
