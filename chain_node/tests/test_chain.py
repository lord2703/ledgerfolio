"""Stage 1: core chain. Any edit to any block must be detected."""

import copy
import unittest

from chain_node.block import Block, genesis_block, meets_target, mine_block
from chain_node.chain import Blockchain, ChainError, chain_work, validate_chain
from chain_node.wallet import Wallet

from .helpers import DIFFICULTY, NETWORK, build_chain, next_block, receipt_tx


class BlockTests(unittest.TestCase):
    def test_genesis_is_deterministic_per_network(self):
        self.assertEqual(genesis_block(NETWORK, 8).hash, genesis_block(NETWORK, 8).hash)
        self.assertNotEqual(genesis_block(NETWORK, 8).hash, genesis_block("other", 8).hash)

    def test_mined_block_meets_difficulty(self):
        block = mine_block(1, "0" * 64, [], difficulty=12)
        self.assertEqual(block.hash, block.compute_hash())
        self.assertTrue(meets_target(block.hash, 12))
        self.assertEqual(int(block.hash, 16) >> (256 - 12), 0)

    def test_hash_changes_when_any_header_field_changes(self):
        block = mine_block(1, "0" * 64, [], difficulty=DIFFICULTY)
        for field, value in [
            ("index", 2),
            ("timestamp", block.timestamp + 1),
            ("previous_hash", "1" * 64),
            ("merkle_root", "2" * 64),
            ("nonce", block.nonce + 1),
            ("difficulty", DIFFICULTY + 1),
        ]:
            edited = copy.copy(block)
            setattr(edited, field, value)
            self.assertNotEqual(edited.compute_hash(), block.hash, field)

    def test_mining_can_be_stopped(self):
        self.assertIsNone(mine_block(1, "0" * 64, [], difficulty=200, should_stop=lambda: True))

    def test_block_round_trips_through_json(self):
        wallet = Wallet.generate()
        block = mine_block(1, "0" * 64, [receipt_tx(wallet, "a")], difficulty=DIFFICULTY)
        self.assertEqual(Block.from_dict(block.to_dict()).to_dict(), block.to_dict())


class ChainValidationTests(unittest.TestCase):
    def setUp(self):
        self.wallet = Wallet.generate()
        self.chain = build_chain(self.wallet, blocks=4, per_block=3)

    def assertInvalid(self, expected_reason):
        valid, reason = self.chain.check()
        self.assertFalse(valid)
        self.assertIn(expected_reason, reason)

    def test_untouched_chain_is_valid(self):
        self.assertEqual(self.chain.check(), (True, None))
        self.assertEqual(self.chain.height, 4)

    def test_editing_a_transaction_is_detected(self):
        block = self.chain.blocks[2]
        forged = receipt_tx(self.wallet, "forged receipt")
        block.transactions[1] = forged
        self.assertInvalid("Merkle root")

    def test_editing_a_transaction_and_fixing_the_merkle_root_is_detected(self):
        block = self.chain.blocks[2]
        block.transactions[1] = receipt_tx(self.wallet, "forged receipt")
        block.merkle_root = block.compute_merkle_root()
        self.assertInvalid("stored hash does not match")

    def test_rehashing_an_edited_block_breaks_the_link_to_the_next(self):
        block = self.chain.blocks[2]
        block.transactions[1] = receipt_tx(self.wallet, "forged receipt")
        remined = mine_block(
            block.index, block.previous_hash, block.transactions, DIFFICULTY, block.timestamp
        )
        self.chain.blocks[2] = remined
        self.assertInvalid("block 3: previous hash")

    def test_editing_each_header_field_is_detected(self):
        for field, value in [
            ("timestamp", lambda b: b.timestamp + 1),
            ("nonce", lambda b: b.nonce + 1),
            ("previous_hash", lambda b: "f" * 64),
            ("merkle_root", lambda b: "e" * 64),
            ("hash", lambda b: "0" * 64),
        ]:
            chain = build_chain(self.wallet)
            block = chain.blocks[1]
            setattr(block, field, value(block))
            valid, _ = chain.check()
            self.assertFalse(valid, field)

    def test_removing_a_block_is_detected(self):
        del self.chain.blocks[2]
        self.assertInvalid("index does not follow")

    def test_reordering_transactions_is_detected(self):
        block = self.chain.blocks[1]
        block.transactions.reverse()
        self.assertInvalid("Merkle root")

    def test_replacing_the_genesis_block_is_detected(self):
        self.chain.blocks[0] = genesis_block("some-other-network", DIFFICULTY)
        self.assertInvalid("genesis")

    def test_block_without_enough_work_is_rejected(self):
        tip = self.chain.tip
        weak = mine_block(tip.index + 1, tip.hash, [], difficulty=0)
        # Claim the network difficulty without having done the work.
        weak.difficulty = DIFFICULTY
        weak.hash = weak.compute_hash()
        if meets_target(weak.hash, DIFFICULTY):  # 1-in-256 fluke: nothing to assert
            return
        with self.assertRaisesRegex(ChainError, "proof-of-work"):
            self.chain.add_block(weak)

    def test_block_below_minimum_difficulty_is_rejected(self):
        with self.assertRaisesRegex(ChainError, "below the network minimum"):
            self.chain.add_block(next_block(self.chain, difficulty=DIFFICULTY - 1))

    def test_block_with_wrong_previous_hash_is_rejected(self):
        orphan = mine_block(self.chain.height + 1, "a" * 64, [], DIFFICULTY)
        with self.assertRaisesRegex(ChainError, "previous hash"):
            self.chain.add_block(orphan)

    def test_block_from_the_future_is_rejected(self):
        tip = self.chain.tip
        future = mine_block(
            tip.index + 1, tip.hash, [], DIFFICULTY, timestamp=tip.timestamp + 10**10
        )
        with self.assertRaisesRegex(ChainError, "future"):
            self.chain.add_block(future)

    def test_duplicate_transaction_across_blocks_is_rejected(self):
        already_confirmed = self.chain.blocks[1].transactions[0]
        with self.assertRaisesRegex(ChainError, "duplicate"):
            self.chain.add_block(next_block(self.chain, [already_confirmed]))

    def test_duplicate_transaction_inside_a_block_is_rejected(self):
        tx = receipt_tx(self.wallet, "twice")
        with self.assertRaisesRegex(ChainError, "duplicate"):
            self.chain.add_block(next_block(self.chain, [tx, tx]))

    def test_chain_loaded_from_tampered_data_is_refused(self):
        data = self.chain.to_list()
        data[2]["transactions"][0]["payload"]["data_hash"] = "ab" * 32
        with self.assertRaises(ChainError):
            Blockchain(NETWORK, DIFFICULTY, [Block.from_dict(item) for item in data])


class ForkResolutionTests(unittest.TestCase):
    def setUp(self):
        self.wallet = Wallet.generate()

    def test_chain_with_more_work_replaces_ours(self):
        ours = build_chain(self.wallet, blocks=2)
        theirs = build_chain(self.wallet, blocks=3)
        orphaned = ours.replace_chain(theirs.blocks)
        self.assertIsNotNone(orphaned)
        self.assertEqual(ours.tip.hash, theirs.tip.hash)

    def test_chain_with_less_or_equal_work_is_ignored(self):
        ours = build_chain(self.wallet, blocks=3)
        tip_before = ours.tip.hash
        self.assertIsNone(ours.replace_chain(build_chain(self.wallet, blocks=2).blocks))
        self.assertIsNone(ours.replace_chain(build_chain(self.wallet, blocks=3).blocks))
        self.assertEqual(ours.tip.hash, tip_before)

    def test_most_work_wins_even_when_the_chain_is_shorter(self):
        # Three blocks at difficulty 8 = 768 work; one block at difficulty 12 = 4096.
        longer = build_chain(self.wallet, blocks=3)
        heavier = Blockchain(NETWORK, DIFFICULTY)
        heavier.add_block(next_block(heavier, [receipt_tx(self.wallet, "x")], difficulty=12))
        self.assertGreater(chain_work(heavier.blocks), chain_work(longer.blocks))
        self.assertIsNotNone(longer.replace_chain(heavier.blocks))
        self.assertEqual(longer.height, 1)

    def test_invalid_chain_never_replaces_ours_however_long(self):
        ours = build_chain(self.wallet, blocks=1)
        theirs = build_chain(self.wallet, blocks=5)
        theirs.blocks[3].nonce += 1
        with self.assertRaises(ChainError):
            ours.replace_chain(theirs.blocks)
        self.assertEqual(ours.height, 1)

    def test_replace_reports_transactions_that_lost_their_block(self):
        ours = Blockchain(NETWORK, DIFFICULTY)
        mine_only = receipt_tx(self.wallet, "only on our fork")
        ours.add_block(next_block(ours, [mine_only]))
        orphaned = ours.replace_chain(build_chain(self.wallet, blocks=2).blocks)
        self.assertEqual([tx.tx_id for tx in orphaned], [mine_only.tx_id])

    def test_chain_from_another_network_is_refused(self):
        other = Blockchain("another-net", DIFFICULTY)
        other.add_block(next_block(other))
        with self.assertRaisesRegex(ChainError, "genesis"):
            validate_chain(other.blocks, NETWORK, DIFFICULTY)


if __name__ == "__main__":
    unittest.main()
