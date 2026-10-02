"""Run a node:  python -m chain_node [--port 8001] [--peers http://127.0.0.1:8002]

Settings come from CHAIN_* environment variables (or a `.env` file in the
current directory); command-line options override them. To try a local network,
start three nodes on different ports and point them at each other:

    python -m chain_node --port 8001
    python -m chain_node --port 8002 --peers http://127.0.0.1:8001
    python -m chain_node --port 8003 --peers http://127.0.0.1:8001,http://127.0.0.1:8002
"""

import argparse
import logging

import uvicorn

from .api import create_app
from .config import NodeConfig
from .node import Node


def main() -> None:
    parser = argparse.ArgumentParser(prog="chain_node", description="Ledgerfolio blockchain node")
    parser.add_argument("--host", help="interface to listen on (default 127.0.0.1)")
    parser.add_argument("--port", type=int, help="port to listen on (default 8001)")
    parser.add_argument("--data-dir", help="where this node stores its chain")
    parser.add_argument("--peers", help="comma-separated peer URLs")
    parser.add_argument("--difficulty", type=int, help="mining difficulty in leading zero bits")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    config = NodeConfig.from_env(
        host=args.host,
        port=args.port,
        data_dir=args.data_dir,
        peers=[p.strip() for p in args.peers.split(",") if p.strip()] if args.peers else None,
        difficulty=args.difficulty,
    )
    node = Node(config)
    logging.getLogger("chain_node").info(
        "Node %s | network %s | height %s | data in %s",
        config.public_url, config.network, node.chain.height, config.data_dir,
    )
    uvicorn.run(create_app(node), host=config.host, port=config.port, log_level="warning")


if __name__ == "__main__":
    main()
