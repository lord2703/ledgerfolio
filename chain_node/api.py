"""HTTP API of a node (FastAPI).

Clients (the Django `ledger` app) and peer nodes use the same endpoints:

    GET  /status                  height, tip, work, mempool size
    GET  /validate                re-validate the whole chain from genesis
    GET  /chain                   every block (used by peers to sync)
    GET  /blocks?limit=10         latest block headers
    GET  /blocks/{index}          one block with its transactions
    POST /blocks                  a block broadcast by a peer
    GET  /mempool                 pending transactions
    POST /transactions            submit a signed transaction
    GET  /transactions/{tx_id}    transaction + block header + Merkle proof
    POST /mine                    mine the mempool into a block now
    GET  /peers, POST /peers      list / register peers
    POST /sync                    compare chains with peers now
"""

from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from . import __version__
from .block import BlockError
from .chain import ChainError
from .node import Node, NodeError
from .transaction import TransactionError


def create_app(node: Node, run_background: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        if run_background:
            node.start()
        yield
        if run_background:
            node.stop()

    app = FastAPI(
        title="Ledgerfolio chain node",
        version=__version__,
        description="A from-scratch blockchain node that records signed receipt hashes.",
        lifespan=lifespan,
    )
    app.state.node = node

    @app.exception_handler(NodeError)
    async def node_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(TransactionError)
    @app.exception_handler(BlockError)
    @app.exception_handler(ChainError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    # --- status ------------------------------------------------------

    @app.get("/status")
    def status():
        return node.status()

    @app.get("/validate")
    def validate(fresh: bool = False):
        valid, reason = node.validate(fresh=fresh)
        return {"valid": valid, "reason": reason, "height": node.chain.height}

    # --- blocks ------------------------------------------------------

    @app.get("/chain")
    def chain():
        with node.lock:
            return {"height": node.chain.height, "blocks": node.chain.to_list()}

    @app.get("/blocks")
    def blocks(limit: int = Query(10, ge=1, le=100)):
        with node.lock:
            latest = node.chain.blocks[-limit:]
            return {"height": node.chain.height, "blocks": [b.header() for b in reversed(latest)]}

    @app.get("/blocks/{index}")
    def block(index: int):
        with node.lock:
            if not 0 <= index <= node.chain.height:
                raise HTTPException(404, "no block at that index")
            return node.chain.blocks[index].to_dict()

    @app.post("/blocks")
    def receive_block(data: dict = Body(...), x_node_url: str | None = Header(None)):
        return {"result": node.receive_block(data, origin=x_node_url)}

    # --- transactions ------------------------------------------------

    @app.get("/mempool")
    def mempool():
        with node.lock:
            return {"count": len(node.mempool), "transactions": node.mempool.to_list()}

    @app.post("/transactions")
    def submit_transaction(data: dict = Body(...), x_node_url: str | None = Header(None)):
        tx, is_new = node.submit_transaction(data, origin=x_node_url)
        return JSONResponse(
            {"tx_id": tx.tx_id, "accepted": is_new},
            status_code=201 if is_new else 200,
        )

    @app.get("/transactions/{tx_id}")
    def transaction(tx_id: str):
        info = node.transaction_info(tx_id)
        if info is None:
            raise HTTPException(404, "transaction not found on this node")
        return info

    @app.post("/mine")
    def mine(allow_empty: bool = False):
        mined = node.mine(allow_empty=allow_empty)
        return {"mined": mined is not None, "block": mined.header() if mined else None}

    # --- peers -------------------------------------------------------

    @app.get("/peers")
    def peers():
        return {"peers": list(node.peers)}

    @app.post("/peers")
    def add_peer(data: dict = Body(...)):
        return {"added": node.add_peer(data.get("url")), "peers": list(node.peers)}

    @app.post("/sync")
    def sync():
        return {"adopted": node.sync(), "height": node.chain.height}

    return app
