"""Stage 6: several nodes. Broadcasting, syncing and most-work fork resolution.

The nodes run in-process and talk to each other through their real HTTP APIs;
only the socket is replaced, by routing each peer URL to that node's app.
"""

import unittest

from fastapi.testclient import TestClient

from chain_node.api import create_app
from chain_node.block import mine_block
from chain_node.storage import MemoryStorage
from chain_node.wallet import Wallet

from .helpers import DIFFICULTY, receipt_tx
from .test_node_api import make_node


class Network:
    def __init__(self):
        self.clients = {}
        self.offline = set()

    def request(self, method, url, json=None, headers=None, timeout=5.0):
        for base, client in self.clients.items():
            if url.startswith(base):
                if base in self.offline:
                    raise ConnectionError(f"{base} is offline")
                response = client.request(method, url[len(base):], json=json, headers=headers)
                return response.status_code, response.json()
        raise ConnectionError(f"no node at {url}")

    def add_node(self, port, peers=(), storage=None, **overrides):
        url = f"http://node-{port}"
        node = make_node(
            storage=storage or MemoryStorage(),
            port=port,
            public_url=url,
            peers=[f"http://node-{p}" for p in peers],
            **overrides,
        )
        node.http = self.request
        self.clients[url] = TestClient(create_app(node, run_background=False))
        node.announce()
        return node


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.wallet = Wallet.generate()
        self.net = Network()
        self.a = self.net.add_node(1)
        self.b = self.net.add_node(2, peers=[1])
        self.c = self.net.add_node(3, peers=[1, 2])
        self.nodes = [self.a, self.b, self.c]

    def tips(self):
        return {node.chain.tip.hash for node in self.nodes}

    def test_peers_learn_about_each_other(self):
        self.assertEqual(sorted(self.a.peers), ["http://node-2", "http://node-3"])
        self.assertEqual(sorted(self.b.peers), ["http://node-1", "http://node-3"])
        self.assertEqual(sorted(self.c.peers), ["http://node-1", "http://node-2"])

    def test_node_does_not_add_itself_or_junk_as_a_peer(self):
        self.assertFalse(self.a.add_peer("http://node-1"))
        self.assertFalse(self.a.add_peer("http://node-1/"))
        self.assertFalse(self.a.add_peer("ftp://somewhere"))
        self.assertFalse(self.a.add_peer(None))
        self.assertFalse(self.a.add_peer("http://node-2"))  # already known

    def test_transaction_is_broadcast_to_every_mempool(self):
        tx, _ = self.a.submit_transaction(receipt_tx(self.wallet, "r1").to_dict())
        for node in self.nodes:
            self.assertIn(tx.tx_id, node.mempool)

    def test_mined_block_is_broadcast_and_clears_every_mempool(self):
        tx, _ = self.a.submit_transaction(receipt_tx(self.wallet, "r1").to_dict())
        block = self.b.mine()
        self.assertEqual(len(self.tips()), 1)
        for node in self.nodes:
            self.assertEqual(node.chain.height, 1)
            self.assertEqual(node.chain.tip.hash, block.hash)
            self.assertEqual(len(node.mempool), 0)
            self.assertEqual(node.transaction_info(tx.tx_id)["status"], "confirmed")

    def test_invalid_block_from_a_peer_is_rejected(self):
        tip = self.a.chain.tip
        block = mine_block(tip.index + 1, tip.hash, [receipt_tx(self.wallet, "x")], DIFFICULTY)
        data = block.to_dict()
        data["transactions"][0]["payload"]["data_hash"] = "ab" * 32
        response = self.net.clients["http://node-1"].post("/blocks", json=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.a.chain.height, 0)

    def test_node_that_was_offline_catches_up(self):
        self.net.offline.add("http://node-3")
        for i in range(3):
            self.a.submit_transaction(receipt_tx(self.wallet, f"r{i}").to_dict())
            self.a.mine()
        self.assertEqual(self.c.chain.height, 0)

        self.net.offline.clear()
        self.assertTrue(self.c.sync())
        self.assertEqual(self.c.chain.height, 3)
        self.assertEqual(len(self.tips()), 1)
        self.assertEqual(self.c.validate(fresh=True), (True, None))

    def test_late_block_triggers_a_sync(self):
        self.net.offline.add("http://node-3")
        self.a.submit_transaction(receipt_tx(self.wallet, "missed").to_dict())
        self.a.mine()
        self.net.offline.clear()
        # C missed block 1, so block 2 does not fit its tip; it must fetch the chain.
        self.a.submit_transaction(receipt_tx(self.wallet, "seen").to_dict())
        self.a.mine()
        self.assertEqual(self.c.chain.height, 2)
        self.assertEqual(len(self.tips()), 1)

    def test_fork_is_resolved_in_favour_of_the_most_work(self):
        # Split the network: A alone, B alone. Each mines its own branch.
        self.net.offline.update({"http://node-1", "http://node-2", "http://node-3"})
        lost, _ = self.a.submit_transaction(receipt_tx(self.wallet, "only on A").to_dict())
        self.a.mine()
        for i in range(2):
            self.b.submit_transaction(receipt_tx(self.wallet, f"on B {i}").to_dict())
            self.b.mine()
        self.assertEqual((self.a.chain.height, self.b.chain.height), (1, 2))
        self.assertNotEqual(self.a.chain.blocks[1].hash, self.b.chain.blocks[1].hash)

        # Heal the split. Everyone converges on B's branch (more work).
        self.net.offline.clear()
        for node in self.nodes:
            node.sync()
        self.assertEqual(self.tips(), {self.b.chain.tip.hash})

        # A's transaction lost its block, so it goes back to the mempool
        # instead of disappearing, and is confirmed by the next block.
        self.assertIn(lost.tx_id, self.a.mempool)
        self.a.mine()
        self.assertEqual(len(self.tips()), 1)
        for node in self.nodes:
            self.assertEqual(node.transaction_info(lost.tx_id)["status"], "confirmed")

    def test_longer_chain_with_less_work_does_not_win(self):
        self.net.offline.update({"http://node-1", "http://node-2", "http://node-3"})
        for i in range(3):  # three blocks at difficulty 8 = 768 work
            self.a.submit_transaction(receipt_tx(self.wallet, f"light {i}").to_dict())
            self.a.mine()
        self.b.config.difficulty = 12  # one block at difficulty 12 = 4096 work
        self.b.submit_transaction(receipt_tx(self.wallet, "heavy").to_dict())
        self.b.mine()

        self.net.offline.clear()
        self.assertTrue(self.a.sync())
        self.assertFalse(self.b.sync())
        self.assertEqual(self.a.chain.height, 1)
        self.assertEqual(self.a.chain.tip.hash, self.b.chain.tip.hash)

    def test_node_ignores_a_peer_on_another_network(self):
        stranger = self.net.add_node(9, network="another-net")
        stranger.submit_transaction(receipt_tx(self.wallet, "x").to_dict())
        stranger.mine()
        self.a.add_peer("http://node-9")
        self.assertFalse(self.a.sync(["http://node-9"]))
        self.assertEqual(self.a.chain.height, 0)

    def test_node_with_a_corrupted_chain_file_heals_from_a_peer(self):
        storage = MemoryStorage()
        d = self.net.add_node(4, peers=[1], storage=storage)
        self.a.submit_transaction(receipt_tx(self.wallet, "r").to_dict())
        self.a.mine()
        self.assertEqual(d.chain.height, 1)

        stored = storage.load("chain")
        stored["blocks"][1]["nonce"] += 1
        storage.save("chain", stored)

        del self.net.clients["http://node-4"]
        restarted = self.net.add_node(4, peers=[1], storage=storage)
        self.assertFalse(restarted.validate()[0])
        self.assertTrue(restarted.sync())
        self.assertEqual(restarted.validate(fresh=True), (True, None))
        self.assertEqual(restarted.chain.tip.hash, self.a.chain.tip.hash)

    def test_offline_peers_do_not_break_submitting_or_mining(self):
        self.net.offline.update({"http://node-2", "http://node-3"})
        self.a.submit_transaction(receipt_tx(self.wallet, "solo").to_dict())
        self.assertIsNotNone(self.a.mine())
        self.assertEqual(self.a.chain.height, 1)


if __name__ == "__main__":
    unittest.main()
