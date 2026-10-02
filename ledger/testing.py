"""Test support: a real blockchain node running in-process.

`LocalNodeMixin` starts a `chain_node` node with in-memory storage and routes
the ledger client's HTTP calls to it, so tests exercise the genuine signing,
mining, Merkle-proof and validation code without opening a socket.
"""

import shutil
import tempfile
from unittest import mock

import httpx
from django.test import override_settings
from fastapi.testclient import TestClient

from chain_node.api import create_app
from chain_node.config import NodeConfig
from chain_node.node import Node
from chain_node.storage import MemoryStorage
from chain_node.wallet import Wallet

from . import services


class LocalNodeMixin:
    """Mix into a Django TestCase. Gives `self.node` and `self.issuer`."""

    node_auto_mine = False

    def setUp(self):
        super().setUp()
        self.issuer = Wallet.generate()
        self.node = self.make_node()
        self.node_online = True

        # Receipt PDFs written during a test go to a throwaway folder.
        files = tempfile.mkdtemp(prefix="ledgerfolio-test-")
        self.addCleanup(shutil.rmtree, files, ignore_errors=True)

        services._wallet_cache.clear()
        overrides = override_settings(
            ISSUER_PRIVATE_KEY=self.issuer.private_hex(), ISSUER_KEY_FILE="",
            CHAIN_NODE_URL="http://node.test", PRIVATE_MEDIA_ROOT=files,
        )
        overrides.enable()
        self.addCleanup(overrides.disable)
        self.addCleanup(services._wallet_cache.clear)

        patcher = mock.patch("ledger.client.send", side_effect=self._route)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_node(self) -> Node:
        config = NodeConfig(
            network="test-net", min_difficulty=4, difficulty=4, auto_mine=self.node_auto_mine,
            synchronous_broadcast=True,
        )
        node = Node(config, storage=MemoryStorage())
        self._http = TestClient(create_app(node, run_background=False))
        return node

    def _route(self, method, url, **kwargs):
        if not self.node_online:
            raise httpx.ConnectError("node is offline")
        kwargs.pop("timeout", None)
        return self._http.request(method, url.replace("http://node.test", ""), **kwargs)
