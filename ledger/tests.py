"""Receipt hashing, anchoring and verification against a real in-process node."""

import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from chain_node.transaction import Transaction
from chain_node.wallet import Wallet
from tracker.models import Client, Payment, Project, Receipt
from tracker.services.receipts import issue_receipt

from . import services
from .client import NodeUnavailable
from .testing import LocalNodeMixin


def make_payment(amount="5000.00", total="12000.00") -> Payment:
    client = Client.objects.create(name="Maria Santos", email="maria@example.com")
    project = Project.objects.create(
        client=client, system_name="Clinic Records System", total_price=Decimal(total)
    )
    return Payment.objects.create(
        project=project, amount=Decimal(amount), date=datetime.date(2026, 9, 1), method="gcash"
    )


class ReceiptHashTests(TestCase):
    def setUp(self):
        self.receipt = issue_receipt(make_payment())

    def test_hash_is_stable_across_a_database_round_trip(self):
        reloaded = Receipt.objects.get(pk=self.receipt.pk)
        self.assertEqual(services.receipt_hash(reloaded), self.receipt.content_hash)
        self.assertRegex(self.receipt.content_hash, r"^[0-9a-f]{64}$")

    def test_every_data_field_changes_the_hash(self):
        original = services.receipt_hash(self.receipt)
        changes = {
            "receipt_number": "RCT-2026-9999",
            "client_name": "Someone Else",
            "system_name": "Another System",
            "amount": Decimal("5000.01"),
            "balance_after": Decimal("0.00"),
            "payment_method": "cash",
            "payment_date": datetime.date(2026, 9, 2),
            "issued_at": self.receipt.issued_at + datetime.timedelta(seconds=1),
            "salt": "0" * 32,
            "document_type": "quotation",
        }
        for field, value in changes.items():
            receipt = Receipt.objects.get(pk=self.receipt.pk)
            setattr(receipt, field, value)
            self.assertNotEqual(services.receipt_hash(receipt), original, field)

    def test_hash_does_not_depend_on_the_pdf_or_ledger_fields(self):
        original = services.receipt_hash(self.receipt)
        self.receipt.tx_id = "ab" * 32
        self.receipt.block_index = 7
        self.receipt.emailed_to = "x@example.com"
        self.assertEqual(services.receipt_hash(self.receipt), original)

    def test_two_receipts_with_the_same_data_hash_differently(self):
        # The random salt stops anyone guessing the data behind a public hash.
        twin = Receipt.objects.get(pk=self.receipt.pk)
        twin.salt = "f" * 32
        self.assertNotEqual(services.receipt_hash(twin), services.receipt_hash(self.receipt))


class AnchorAndVerifyTests(LocalNodeMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.receipt = issue_receipt(make_payment())

    def anchor(self):
        services.anchor(self.receipt)
        self.receipt.refresh_from_db()
        return self.receipt

    def check(self, key, result):
        return next(check for check in result.checks if check.key == key)

    # --- anchoring -----------------------------------------------------

    def test_anchor_signs_mines_and_confirms(self):
        receipt = self.anchor()
        self.assertEqual(receipt.ledger_status, Receipt.LedgerStatus.CONFIRMED)
        self.assertEqual(receipt.block_index, 1)
        self.assertEqual(self.node.chain.height, 1)

        tx = self.node.chain.blocks[1].transactions[0]
        self.assertEqual(tx.tx_id, receipt.tx_id)
        self.assertEqual(tx.sender, self.issuer.public_key_hex)
        self.assertEqual(tx.payload, {"type": "receipt", "data_hash": receipt.content_hash})

    def test_only_the_hash_goes_on_chain(self):
        receipt = self.anchor()
        on_chain = str(self.node.chain.to_list())
        for private in ("Maria", "Santos", "Clinic", "5000", receipt.receipt_number):
            self.assertNotIn(private, on_chain)

    def test_anchoring_twice_does_not_create_a_second_transaction(self):
        first = self.anchor().tx_id
        second = self.anchor().tx_id
        self.assertEqual(first, second)
        self.assertEqual(self.node.chain.transaction_count, 1)

    def test_changed_receipt_cannot_be_anchored_again(self):
        self.anchor()
        self.receipt.amount = Decimal("1.00")
        with self.assertRaisesRegex(services.LedgerError, "changed after it was anchored"):
            services.anchor(self.receipt)

    def test_anchor_reports_an_unreachable_node(self):
        self.node_online = False
        with self.assertRaisesRegex(services.LedgerError, "not reachable"):
            services.anchor(self.receipt)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.ledger_status, Receipt.LedgerStatus.UNANCHORED)

    def test_anchor_without_an_issuer_key_is_a_clear_error(self):
        services._wallet_cache.clear()
        with self.settings(ISSUER_PRIVATE_KEY="", ISSUER_KEY_FILE=""):
            with self.assertRaisesRegex(services.LedgerError, "No issuer key"):
                services.anchor(self.receipt)

    def test_stored_transaction_can_be_resent_to_a_node_that_lost_it(self):
        tx_id = self.anchor().tx_id
        self.node = self.make_node()  # a fresh, empty node
        self.anchor()
        self.assertEqual(self.receipt.tx_id, tx_id)
        self.assertTrue(self.node.chain.has_transaction(tx_id))

    # --- verification ----------------------------------------------------

    def test_untouched_receipt_is_valid(self):
        result = services.verify(self.anchor())
        self.assertEqual(result.state, services.VALID)
        self.assertTrue(all(check.passed for check in result.checks))
        self.assertEqual(result.block["index"], 1)
        self.assertEqual(result.confirmations, 1)

    def test_edited_receipt_data_is_tampered(self):
        receipt = self.anchor()
        Receipt.objects.filter(pk=receipt.pk).update(amount=Decimal("9999.00"))
        result = services.verify(Receipt.objects.get(pk=receipt.pk))
        self.assertEqual(result.state, services.TAMPERED)
        self.assertFalse(self.check("data", result).passed)

    def test_editing_data_and_its_stored_hash_together_is_still_caught_by_the_chain(self):
        receipt = self.anchor()
        receipt.amount = Decimal("9999.00")
        receipt.content_hash = services.receipt_hash(receipt)
        receipt.save()
        result = services.verify(receipt)
        self.assertEqual(result.state, services.TAMPERED)
        self.assertTrue(self.check("data", result).passed)
        self.assertFalse(self.check("ledger", result).passed)

    def test_transaction_missing_from_the_chain_is_tampered(self):
        receipt = self.anchor()
        self.node = self.make_node()
        result = services.verify(receipt)
        self.assertEqual(result.state, services.TAMPERED)
        self.assertIn("missing", result.summary)

    def test_transaction_signed_by_someone_else_is_tampered(self):
        # An attacker with database access re-anchors an edited receipt with their own key.
        receipt = self.anchor()
        receipt.amount = Decimal("1.00")
        forged_hash = services.receipt_hash(receipt)
        forged = Transaction.create(Wallet.generate(), {"type": "receipt", "data_hash": forged_hash})
        self.node.submit_transaction(forged.to_dict())
        self.node.mine()
        receipt.content_hash, receipt.tx_id = forged_hash, forged.tx_id
        receipt.save()

        result = services.verify(receipt)
        self.assertEqual(result.state, services.TAMPERED)
        self.assertTrue(self.check("ledger", result).passed)
        self.assertFalse(self.check("signature", result).passed)

    def test_edited_block_makes_the_chain_invalid(self):
        receipt = self.anchor()
        other = Transaction.create(self.issuer, {"type": "receipt", "data_hash": "ab" * 32})
        self.node.submit_transaction(other.to_dict())
        self.node.mine()
        self.node.chain.blocks[2].nonce += 1  # someone edits history
        self.node._validation_cache = None

        result = services.verify(receipt)
        self.assertEqual(result.state, services.TAMPERED)
        self.assertFalse(self.check("chain", result).passed)

    def test_unmined_transaction_is_pending_not_valid(self):
        with mock.patch("ledger.client.NodeClient.mine", side_effect=NodeUnavailable("busy")):
            services.anchor(self.receipt)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.ledger_status, Receipt.LedgerStatus.PENDING)
        result = services.verify(self.receipt)
        self.assertEqual(result.state, services.PENDING)
        self.assertTrue(self.check("signature", result).passed)
        self.assertIsNone(self.check("block", result).passed)

        self.node.mine()
        self.assertEqual(services.verify(self.receipt).state, services.VALID)
        services.refresh(self.receipt)
        self.assertEqual(self.receipt.ledger_status, Receipt.LedgerStatus.CONFIRMED)

    def test_receipt_never_anchored_is_pending(self):
        result = services.verify(self.receipt)
        self.assertEqual(result.state, services.PENDING)

    def test_unreachable_node_is_unavailable_not_tampered(self):
        receipt = self.anchor()
        self.node_online = False
        result = services.verify(receipt)
        self.assertEqual(result.state, services.UNAVAILABLE)

    def test_overview(self):
        self.anchor()
        overview = services.overview()
        self.assertTrue(overview["online"])
        self.assertTrue(overview["valid"])
        self.assertEqual([block["index"] for block in overview["blocks"]], [1, 0])
        self.node_online = False
        self.assertEqual(services.overview(), {"online": False})
