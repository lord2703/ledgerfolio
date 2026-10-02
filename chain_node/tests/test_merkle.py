"""Stage 3: Merkle tree and proofs."""

import unittest

from chain_node.crypto import sha256_hex
from chain_node.merkle import EMPTY_ROOT, leaf_hash, merkle_proof, merkle_root, verify_proof
from chain_node.wallet import Wallet

from .helpers import build_chain


def ids(count):
    return [sha256_hex(f"tx-{i}".encode()) for i in range(count)]


class MerkleTests(unittest.TestCase):
    def test_empty_and_single(self):
        self.assertEqual(merkle_root([]), EMPTY_ROOT)
        (only,) = ids(1)
        self.assertEqual(merkle_root([only]), leaf_hash(only))
        self.assertEqual(merkle_proof([only], 0), [])
        self.assertTrue(verify_proof(only, [], merkle_root([only])))

    def test_every_leaf_has_a_valid_proof_for_any_size(self):
        for count in range(1, 18):
            tx_ids = ids(count)
            root = merkle_root(tx_ids)
            for index, tx_id in enumerate(tx_ids):
                proof = merkle_proof(tx_ids, index)
                self.assertTrue(verify_proof(tx_id, proof, root), (count, index))

    def test_root_depends_on_content_and_order(self):
        tx_ids = ids(5)
        root = merkle_root(tx_ids)
        self.assertNotEqual(root, merkle_root(tx_ids[:-1]))
        self.assertNotEqual(root, merkle_root(list(reversed(tx_ids))))
        self.assertNotEqual(root, merkle_root(tx_ids[:2] + [sha256_hex(b"swap")] + tx_ids[3:]))

    def test_proof_fails_for_a_transaction_not_in_the_block(self):
        tx_ids = ids(6)
        root = merkle_root(tx_ids)
        proof = merkle_proof(tx_ids, 2)
        self.assertFalse(verify_proof(sha256_hex(b"outsider"), proof, root))

    def test_proof_fails_when_tampered(self):
        tx_ids = ids(6)
        root = merkle_root(tx_ids)
        proof = merkle_proof(tx_ids, 2)

        wrong_hash = [dict(step) for step in proof]
        wrong_hash[0]["hash"] = sha256_hex(b"wrong")
        self.assertFalse(verify_proof(tx_ids[2], wrong_hash, root))

        wrong_side = [dict(step) for step in proof]
        wrong_side[0]["position"] = "left" if proof[0]["position"] == "right" else "right"
        self.assertFalse(verify_proof(tx_ids[2], wrong_side, root))

        self.assertFalse(verify_proof(tx_ids[2], proof[:-1], root))
        self.assertFalse(verify_proof(tx_ids[2], proof, sha256_hex(b"other root")))

    def test_malformed_proof_is_false_not_an_error(self):
        tx_id = ids(1)[0]
        self.assertFalse(verify_proof(tx_id, [{"hash": "zz", "position": "left"}], EMPTY_ROOT))
        self.assertFalse(verify_proof(tx_id, [{"position": "left"}], EMPTY_ROOT))
        self.assertFalse(verify_proof(tx_id, ["nope"], EMPTY_ROOT))

    def test_inner_node_cannot_pose_as_a_leaf(self):
        tx_ids = ids(4)
        root = merkle_root(tx_ids)
        # The root of the left pair is an inner node; it must not verify as a tx.
        left_pair_root = merkle_root(tx_ids[:2])
        right_pair_root = merkle_root(tx_ids[2:])
        self.assertFalse(
            verify_proof(left_pair_root, [{"hash": right_pair_root, "position": "right"}], root)
        )

    def test_index_out_of_range(self):
        with self.assertRaises(IndexError):
            merkle_proof(ids(3), 3)

    def test_chain_gives_proofs_for_confirmed_transactions(self):
        chain = build_chain(Wallet.generate(), blocks=2, per_block=5)
        for block in chain.blocks[1:]:
            self.assertEqual(block.merkle_root, block.compute_merkle_root())
            for tx in block.transactions:
                self.assertTrue(verify_proof(tx.tx_id, chain.proof_for(tx.tx_id), block.merkle_root))
        self.assertIsNone(chain.proof_for(sha256_hex(b"unknown")))


if __name__ == "__main__":
    unittest.main()
