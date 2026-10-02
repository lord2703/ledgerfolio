"""Stage 2: wallets and signed transactions."""

import dataclasses
import unittest

from chain_node.crypto import sha256_hex
from chain_node.transaction import Transaction, TransactionError
from chain_node.wallet import Wallet, WalletError, verify_signature

from .helpers import receipt_tx


class WalletTests(unittest.TestCase):
    def test_sign_and_verify(self):
        wallet = Wallet.generate()
        signature = wallet.sign(b"receipt")
        self.assertTrue(verify_signature(wallet.public_key_hex, b"receipt", signature))

    def test_signature_fails_for_other_message_or_other_key(self):
        wallet, other = Wallet.generate(), Wallet.generate()
        signature = wallet.sign(b"receipt")
        self.assertFalse(verify_signature(wallet.public_key_hex, b"edited", signature))
        self.assertFalse(verify_signature(other.public_key_hex, b"receipt", signature))

    def test_garbage_never_verifies_or_raises(self):
        wallet = Wallet.generate()
        self.assertFalse(verify_signature(wallet.public_key_hex, b"x", "not hex"))
        self.assertFalse(verify_signature("zz", b"x", wallet.sign(b"x")))
        self.assertFalse(verify_signature(wallet.public_key_hex, b"x", "00" * 70))

    def test_key_survives_hex_and_pem_round_trips(self):
        wallet = Wallet.generate()
        self.assertEqual(
            Wallet.from_private_hex(wallet.private_hex()).public_key_hex, wallet.public_key_hex
        )
        self.assertEqual(Wallet.from_pem(wallet.to_pem()).public_key_hex, wallet.public_key_hex)
        encrypted = wallet.to_pem(password=b"secret")
        self.assertEqual(
            Wallet.from_pem(encrypted, password=b"secret").public_key_hex, wallet.public_key_hex
        )

    def test_public_key_is_compressed_secp256k1(self):
        public = Wallet.generate().public_key_hex
        self.assertEqual(len(public), 66)
        self.assertIn(public[:2], ("02", "03"))

    def test_repr_does_not_leak_the_private_key(self):
        wallet = Wallet.generate()
        self.assertNotIn(wallet.private_hex(), repr(wallet))

    def test_bad_private_key_is_rejected(self):
        with self.assertRaises(WalletError):
            Wallet.from_private_hex("not a key")
        with self.assertRaises(WalletError):
            Wallet.from_pem(b"not a pem")


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.wallet = Wallet.generate()
        self.tx = receipt_tx(self.wallet, "receipt RCT-2026-0001")

    def assertRejected(self, reason, **changes):
        tampered = dataclasses.replace(self.tx, **changes)
        with self.assertRaisesRegex(TransactionError, reason):
            tampered.validate()

    def test_signed_transaction_is_valid(self):
        self.tx.validate()
        self.assertTrue(self.tx.is_valid())

    def test_round_trips_through_json(self):
        restored = Transaction.from_dict(self.tx.to_dict())
        self.assertEqual(restored, self.tx)
        restored.validate()

    def test_changed_payload_is_rejected(self):
        payload = {"type": "receipt", "data_hash": sha256_hex(b"a different receipt")}
        self.assertRejected("id does not match", payload=payload)

    def test_changed_payload_with_recomputed_id_fails_the_signature(self):
        payload = {"type": "receipt", "data_hash": sha256_hex(b"a different receipt")}
        forged = dataclasses.replace(self.tx, payload=payload)
        forged = dataclasses.replace(forged, tx_id=forged.compute_id())
        with self.assertRaisesRegex(TransactionError, "signature"):
            forged.validate()

    def test_changed_timestamp_is_rejected(self):
        self.assertRejected("id does not match", timestamp=self.tx.timestamp + 1)

    def test_signature_from_another_wallet_is_rejected(self):
        impostor = Wallet.generate()
        self.assertRejected("signature", signature=impostor.sign(self.tx.signing_bytes()))

    def test_claiming_another_sender_is_rejected(self):
        forged = dataclasses.replace(self.tx, sender=Wallet.generate().public_key_hex)
        forged = dataclasses.replace(forged, tx_id=forged.compute_id())
        with self.assertRaisesRegex(TransactionError, "signature"):
            forged.validate()

    def test_payload_may_only_carry_a_hash(self):
        for payload in (
            {"type": "receipt", "data_hash": "not-a-hash"},
            {"type": "receipt", "data_hash": "AB" * 32},
            {"type": "receipt"},
            {"type": "", "data_hash": sha256_hex(b"x")},
            {"type": "receipt", "data_hash": sha256_hex(b"x"), "client_name": "Maria"},
            "receipt",
        ):
            with self.assertRaisesRegex(TransactionError, "payload", msg=payload):
                dataclasses.replace(self.tx, payload=payload).validate()

    def test_malformed_fields_are_rejected(self):
        self.assertRejected("public key", sender="1234")
        self.assertRejected("timestamp", timestamp="yesterday")
        self.assertRejected("timestamp", timestamp=-5)
        self.assertRejected("signature", signature="")

    def test_missing_fields_are_rejected(self):
        data = self.tx.to_dict()
        del data["signature"]
        with self.assertRaisesRegex(TransactionError, "missing"):
            Transaction.from_dict(data)

    def test_same_content_at_another_time_is_a_different_transaction(self):
        first = receipt_tx(self.wallet, "same", timestamp=1000)
        second = receipt_tx(self.wallet, "same", timestamp=2000)
        self.assertNotEqual(first.tx_id, second.tx_id)


if __name__ == "__main__":
    unittest.main()
