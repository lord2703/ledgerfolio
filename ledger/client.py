"""Thin HTTP client for a blockchain node's API."""

import httpx
from django.conf import settings


class NodeUnavailable(Exception):
    """The node could not be reached or answered with a server error."""


class NodeRejected(Exception):
    """The node understood the request and refused it (e.g. invalid transaction)."""


_http = None


def send(method: str, url: str, **kwargs):
    """One shared connection pool for every call to the node.

    Creating an HTTP client per request costs a few hundred milliseconds, which
    adds up fast on pages that ask the node several things.
    """
    global _http
    if _http is None:
        _http = httpx.Client()
    return _http.request(method, url, **kwargs)


class NodeClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or settings.CHAIN_NODE_URL).rstrip("/")
        self.timeout = timeout or settings.CHAIN_NODE_TIMEOUT

    def _request(self, method: str, path: str, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        try:
            response = send(method, f"{self.base_url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise NodeUnavailable(f"could not reach the node at {self.base_url}") from exc
        if response.status_code >= 500:
            raise NodeUnavailable(self._detail(response))
        return response

    @staticmethod
    def _detail(response) -> str:
        try:
            return str(response.json().get("detail", response.text))
        except ValueError:
            return response.text

    def _json(self, method: str, path: str, **kwargs):
        response = self._request(method, path, **kwargs)
        if response.status_code >= 400:
            raise NodeRejected(self._detail(response))
        return response.json()

    # --- API -----------------------------------------------------------

    def status(self) -> dict:
        return self._json("GET", "/status")

    def validate(self) -> dict:
        return self._json("GET", "/validate")

    def latest_blocks(self, limit: int = 10) -> list:
        return self._json("GET", "/blocks", params={"limit": limit})["blocks"]

    def submit_transaction(self, tx: dict) -> dict:
        return self._json("POST", "/transactions", json=tx)

    def get_transaction(self, tx_id: str) -> dict | None:
        """Transaction, block header and Merkle proof; None if the node has no such tx."""
        response = self._request("GET", f"/transactions/{tx_id}")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise NodeRejected(self._detail(response))
        return response.json()

    def mine(self, timeout: float | None = None) -> dict:
        return self._json("POST", "/mine", timeout=timeout or self.timeout)
