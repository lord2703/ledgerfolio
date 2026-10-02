"""Stage 4: mempool, mining and the HTTP API of a single node."""

import unittest

from fastapi.testclient import TestClient

from chain_node.api import create_app
from chain_node.block import meets_target
from chain_node.config import NodeConfig
from chain_node.merkle import verify_proof
from chain_node.node import Node
from chain_node.storage import MemoryStorage
from chain_node.transaction import Transaction
from chain_node.wallet import Wallet

from .helpers import DIFFICULTY, NETWORK, receipt_tx


def make_node(storage=None, **overrides) -> Node:
    settings = {
        "network": NETWORK,
        "min_difficulty": DIFFICULTY,
        "difficulty": DIFFICULTY,
        "auto_mine": False,
        "synchronous_broadcast": True,
    }
    settings.update(overrides)
    return Node(NodeConfig(**settings), storage=storage or MemoryStorage())


class NodeApiTests(unittest.TestCase):
    def setUp(self):
        self.wallet = Wallet.generate()
        self.node = make_node()
        self.client = TestClient(create_app(self.node, run_background=False))

    def submit(self, label="receipt"):
        tx = receipt_tx(self.wallet, label)
        response = self.client.post("/transactions", json=tx.to_dict())
        return tx, response

    def test_fresh_node_has_only_genesis(self):
        status = self.client.get("/status").json()
        self.assertEqual(status["height"], 0)
        self.assertEqual(status["mempool"], 0)
        self.assertTrue(status["healthy"])
        self.assertEqual(self.client.get("/validate").json()["valid"], True)

    def test_submitted_transaction_waits_in_the_mempool(self):
        tx, response = self.submit()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"tx_id": tx.tx_id, "accepted": True})
        self.assertEqual(self.client.get("/mempool").json()["count"], 1)
        info = self.client.get(f"/transactions/{tx.tx_id}").json()
        self.assertEqual(info["status"], "pending")
        self.assertNotIn("proof", info)

    def test_submitting_twice_is_not_a_duplicate(self):
        tx, _ = self.submit()
        again = self.client.post("/transactions", json=tx.to_dict())
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.json()["accepted"])
        self.assertEqual(self.client.get("/mempool").json()["count"], 1)

    def test_invalid_transactions_are_rejected(self):
        tx = receipt_tx(self.wallet, "receipt")
        forged = tx.to_dict()
        forged["payload"]["data_hash"] = "ab" * 32
        self.assertEqual(self.client.post("/transactions", json=forged).status_code, 400)

        unsigned = tx.to_dict()
        unsigned["signature"] = Wallet.generate().sign(tx.signing_bytes())
        self.assertEqual(self.client.post("/transactions", json=unsigned).status_code, 400)

        self.assertEqual(self.client.post("/transactions", json={"hello": 1}).status_code, 400)
        self.assertEqual(self.client.get("/mempool").json()["count"], 0)

    def test_mining_moves_transactions_into_a_valid_block(self):
        txs = [self.submit(f"receipt-{i}")[0] for i in range(3)]
        mined = self.client.post("/mine").json()
        self.assertTrue(mined["mined"])
        self.assertEqual(mined["block"]["index"], 1)
        self.assertEqual(mined["block"]["tx_count"], 3)
        self.assertTrue(meets_target(mined["block"]["hash"], DIFFICULTY))
        self.assertEqual(self.client.get("/mempool").json()["count"], 0)
        self.assertEqual(self.client.get("/validate?fresh=true").json()["valid"], True)

        for tx in txs:
            info = self.client.get(f"/transactions/{tx.tx_id}").json()
            self.assertEqual(info["status"], "confirmed")
            self.assertEqual(info["confirmations"], 1)
            self.assertEqual(Transaction.from_dict(info["transaction"]), tx)
            self.assertTrue(verify_proof(tx.tx_id, info["proof"], info["block"]["merkle_root"]))

    def test_nothing_to_mine(self):
        self.assertEqual(self.client.post("/mine").json(), {"mined": False, "block": None})
        self.assertTrue(self.client.post("/mine?allow_empty=true").json()["mined"])

    def test_confirmed_transaction_cannot_be_submitted_again(self):
        tx, _ = self.submit()
        self.client.post("/mine")
        again = self.client.post("/transactions", json=tx.to_dict())
        self.assertFalse(again.json()["accepted"])
        self.assertEqual(self.client.get("/mempool").json()["count"], 0)

    def test_unknown_transaction_and_block_are_404(self):
        self.assertEqual(self.client.get("/transactions/" + "0" * 64).status_code, 404)
        self.assertEqual(self.client.get("/blocks/99").status_code, 404)

    def test_block_listing(self):
        self.submit()
        self.client.post("/mine")
        listing = self.client.get("/blocks?limit=5").json()
        self.assertEqual([b["index"] for b in listing["blocks"]], [1, 0])
        block = self.client.get("/blocks/1").json()
        self.assertEqual(len(block["transactions"]), 1)

    def test_tampering_with_the_live_chain_is_reported(self):
        self.submit("first")
        self.client.post("/mine")
        self.submit("second")
        self.client.post("/mine")
        self.node.chain.blocks[1].transactions[0] = receipt_tx(self.wallet, "forged")
        report = self.client.get("/validate?fresh=true").json()
        self.assertFalse(report["valid"])
        self.assertIn("block 1", report["reason"])

    def test_sender_allow_list(self):
        node = make_node(allowed_senders=[self.wallet.public_key_hex])
        client = TestClient(create_app(node, run_background=False))
        ok = client.post("/transactions", json=receipt_tx(self.wallet, "mine").to_dict())
        stranger = client.post(
            "/transactions", json=receipt_tx(Wallet.generate(), "theirs").to_dict()
        )
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(stranger.status_code, 403)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.wallet = Wallet.generate()
        self.storage = MemoryStorage()

    def test_chain_and_mempool_survive_a_restart(self):
        node = make_node(self.storage)
        node.submit_transaction(receipt_tx(self.wallet, "confirmed").to_dict())
        node.mine()
        pending, _ = node.submit_transaction(receipt_tx(self.wallet, "pending").to_dict())

        restarted = make_node(self.storage)
        self.assertEqual(restarted.chain.height, 1)
        self.assertEqual(restarted.chain.tip.hash, node.chain.tip.hash)
        self.assertIn(pending.tx_id, restarted.mempool)
        self.assertEqual(restarted.validate(), (True, None))

    def test_chain_file_edited_on_disk_is_detected_at_startup(self):
        node = make_node(self.storage)
        node.submit_transaction(receipt_tx(self.wallet, "original").to_dict())
        node.mine()

        stored = self.storage.load("chain")
        stored["blocks"][1]["transactions"][0]["payload"]["data_hash"] = "cd" * 32
        self.storage.save("chain", stored)

        restarted = make_node(self.storage)
        valid, reason = restarted.validate()
        self.assertFalse(valid)
        self.assertIn("block 1", reason)
        self.assertFalse(restarted.status()["healthy"])

        client = TestClient(create_app(restarted, run_background=False))
        refused = client.post("/transactions", json=receipt_tx(self.wallet, "new").to_dict())
        self.assertEqual(refused.status_code, 503)
        self.assertEqual(client.post("/mine").status_code, 503)


if __name__ == "__main__":
    unittest.main()
