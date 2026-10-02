"""Node configuration, read from CHAIN_* environment variables.

For convenience the node also reads CHAIN_* lines from a `.env` file in the
working directory (the same file Django uses), without depending on Django or
any env library. Real environment variables always win over the file.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = 8001


def _read_env_file(path: Path) -> dict:
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("CHAIN_"):
            values[key] = value.strip().strip("'\"")
    return values


def _as_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value):
    return [item.strip() for item in str(value).split(",") if item.strip()]


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


@dataclass
class NodeConfig:
    # Consensus parameters: every node on the network must use the same values.
    network: str = "ledgerfolio-dev"
    min_difficulty: int = 12

    # Local settings.
    difficulty: int = 12  # difficulty this node mines at (>= min_difficulty)
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    data_dir: str = "chain_data/node-8001"
    public_url: str = ""  # how peers reach this node
    peers: list = field(default_factory=list)
    auto_mine: bool = True
    allowed_senders: list = field(default_factory=list)  # empty = accept any signer
    sync_interval: float = 30.0
    max_mempool: int = 5000
    # Tests set this so broadcasts finish before the call returns.
    synchronous_broadcast: bool = False

    def __post_init__(self):
        if not 0 <= self.min_difficulty <= 255:
            raise ValueError("CHAIN_MIN_DIFFICULTY must be between 0 and 255")
        if self.difficulty < self.min_difficulty:
            raise ValueError("CHAIN_DIFFICULTY cannot be below CHAIN_MIN_DIFFICULTY")
        if not self.public_url:
            self.public_url = f"http://{self.host}:{self.port}"
        self.public_url = normalize_url(self.public_url)
        self.peers = [normalize_url(peer) for peer in self.peers]

    @classmethod
    def from_env(cls, env_file=".env", **overrides) -> "NodeConfig":
        env = {**_read_env_file(Path(env_file)), **os.environ}

        def get(name, default):
            return env.get(f"CHAIN_{name}", default)

        port = int(overrides.get("port") or get("PORT", DEFAULT_PORT))
        min_difficulty = int(get("MIN_DIFFICULTY", 12))
        values = {
            "network": get("NETWORK", "ledgerfolio-dev"),
            "min_difficulty": min_difficulty,
            "difficulty": int(get("DIFFICULTY", min_difficulty)),
            "host": get("HOST", "127.0.0.1"),
            "port": port,
            "data_dir": get("DATA_DIR", "") or f"chain_data/node-{port}",
            "public_url": get("PUBLIC_URL", ""),
            "peers": _as_list(get("PEERS", "")),
            "auto_mine": _as_bool(get("AUTO_MINE", "true")),
            "allowed_senders": _as_list(get("ALLOWED_SENDERS", "")),
            "sync_interval": float(get("SYNC_INTERVAL", 30)),
        }
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**values)
