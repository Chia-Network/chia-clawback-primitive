from __future__ import annotations

import asyncio
from pathlib import Path
from sqlite3 import IntegrityError
from typing import AsyncGenerator, Tuple

import pytest
import pytest_asyncio
from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.rpc_server import start_rpc_server
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.setup_nodes import setup_simulators_and_wallets
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint16, uint32
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet

from src.cb_coin_record import CBCoinRecord, CBCoinState
from src.cb_coin_store import CBCoinStore
from src.cb_wallet_store import CBWalletStore


@pytest_asyncio.fixture(scope="function")
async def node_and_wallet():
    sims = setup_simulators_and_wallets(1, 1, {})
    async for _ in sims:
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_wallets():
    sims = setup_simulators_and_wallets(1, 2, {})
    async for _ in sims:
        yield _


@pytest_asyncio.fixture(scope="function")
async def maker_taker_rpc(
    two_wallets,
) -> AsyncGenerator[
    Tuple[Wallet, WalletRpcClient, Wallet, WalletRpcClient, FullNodeSimulator, FullNodeRpcClient], None
]:
    full_nodes, wallets, bt = two_wallets
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server

    wallet_node_maker, server_0 = wallets[0]
    wallet_node_taker, server_1 = wallets[1]
    wallet_maker: Wallet = wallet_node_maker.wallet_state_manager.main_wallet
    wallet_taker: Wallet = wallet_node_taker.wallet_state_manager.main_wallet

    wallet_node_maker.config["trusted_peers"] = {
        full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
    }
    wallet_node_taker.config["trusted_peers"] = {
        full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
    }

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    api_maker = WalletRpcApi(wallet_node_maker)
    api_taker = WalletRpcApi(wallet_node_taker)
    config = bt.config
    daemon_port = config["daemon_port"]
    self_hostname = config["self_hostname"]

    def stop_node_cb() -> None:
        pass

    full_node_rpc_api = FullNodeRpcApi(full_node_api.full_node)

    rpc_server_node = await start_rpc_server(
        full_node_rpc_api,
        self_hostname,
        daemon_port,
        uint16(0),
        stop_node_cb,
        bt.root_path,
        config,
        connect_to_daemon=False,
    )

    rpc_server_maker = await start_rpc_server(
        api_maker,
        self_hostname,
        daemon_port,
        uint16(0),
        lambda x: None,  # type: ignore
        bt.root_path,
        config,
        connect_to_daemon=False,
    )

    rpc_server_taker = await start_rpc_server(
        api_taker,
        self_hostname,
        daemon_port,
        uint16(0),
        lambda x: None,  # type: ignore
        bt.root_path,
        config,
        connect_to_daemon=False,
    )

    client_maker: WalletRpcClient = await WalletRpcClient.create(
        self_hostname, rpc_server_maker.listen_port, bt.root_path, config
    )
    client_taker: WalletRpcClient = await WalletRpcClient.create(
        self_hostname, rpc_server_taker.listen_port, bt.root_path, config
    )
    client_node: FullNodeRpcClient = await FullNodeRpcClient.create(
        self_hostname, rpc_server_node.listen_port, bt.root_path, config
    )

    yield wallet_maker, client_maker, wallet_taker, client_taker, full_node_api, client_node

    client_maker.close()
    client_taker.close()
    client_node.close()
    rpc_server_maker.close()
    rpc_server_taker.close()
    rpc_server_node.close()
    await client_maker.await_closed()
    await client_taker.await_closed()
    await client_node.await_closed()
    await rpc_server_maker.await_closed()
    await rpc_server_taker.await_closed()
    await rpc_server_node.await_closed()


@pytest.mark.asyncio
async def test_cb_stores(
    tmp_path: Path,
    maker_taker_rpc: Tuple[Wallet, WalletRpcClient, Wallet, WalletRpcClient, FullNodeSimulator, FullNodeRpcClient],
) -> None:
    wallet_maker, client_maker, _, _, node_api, node_client = maker_taker_rpc
    # wallet_maker: WalletRpcClient = wallet_maker
    db_path = tmp_path / "clawback.db"
    db_wrapper = await DBWrapper2.create(database=db_path, reader_count=1, db_version=1)
    wallet_db = await CBWalletStore.create(db_wrapper)
    await wallet_db.create_wallet("cat", WalletType.CAT.value, "")
    await wallet_db.create_wallet("nft", WalletType.NFT.value, "")

    wallets = await wallet_db.get_all_wallet_info_entries()
    assert len(wallets) == 3

    with pytest.raises(IntegrityError) as excinfo:
        await wallet_db.create_wallet("nft", WalletType.NFT.value, "")
    assert "UNIQUE constraint failed" in str(excinfo.value)

    ph_maker = await wallet_maker.get_new_puzzlehash()
    await wallet_db.add_inner_puzzle_hash(ph_maker)
    phs = await wallet_db.get_inner_puzzle_hashes()
    assert phs[0] == ph_maker

    await node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await asyncio.sleep(5)
    coin_db = await CBCoinStore.create(db_wrapper)
    coin = (await client_maker.select_coins(100, 1))[0]

    coin_rec = CBCoinRecord(coin, uint32(0), uint32(0), False, False, WalletType.STANDARD_WALLET, 1, CBCoinState.LOCKED)
    await coin_db.add_coin_record(coin_rec)
    cb_coin_rec = await coin_db.get_coin_record(coin.name())
    assert cb_coin_rec.state == CBCoinState.LOCKED

    await db_wrapper.close()
