from __future__ import annotations

from pathlib import Path
from secrets import token_bytes
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
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint16, uint64
from chia.wallet.wallet import Wallet

from src.drivers.cb_manager import TWO_WEEKS, CBManager
from src.drivers.cb_store import CBStore


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

    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_taker = await wallet_taker.get_new_puzzlehash()
    ph_token = bytes32(token_bytes(32))

    wallet_node_maker.config["trusted_peers"] = {
        full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
    }
    wallet_node_taker.config["trusted_peers"] = {
        full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
    }

    await server_0.start_client(PeerInfo("127.0.0.1", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("127.0.0.1", uint16(full_node_server._port)), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_taker))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    api_maker = WalletRpcApi(wallet_node_maker)
    api_taker = WalletRpcApi(wallet_node_taker)
    config = bt.config
    daemon_port = config["daemon_port"]
    self_hostname = config["self_hostname"]

    def stop_node_cb() -> None:
        pass

    full_node_rpc_api = FullNodeRpcApi(full_node_api.full_node)

    rpc_server_node = await start_rpc_server(
        full_node_rpc_api,  # type: ignore
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
async def test_clawback(
    tmp_path: Path,
    maker_taker_rpc: Tuple[Wallet, WalletRpcClient, Wallet, WalletRpcClient, FullNodeSimulator, FullNodeRpcClient],
) -> None:
    wallet_maker, client_maker, wallet_taker, client_taker, full_node_api, node_client = maker_taker_rpc
    amount = uint64(100000000)
    timelock = TWO_WEEKS
    ph_token = bytes32(token_bytes(32))
    ph_maker = await wallet_maker.get_new_puzzlehash()
    ph_taker = await wallet_taker.get_new_puzzlehash()
    fee = uint64(10)

    # setup for maker
    db_path = tmp_path / "clawback.db"
    wrapper = await DBWrapper2.create(database=db_path)
    cb_store = await CBStore.create(wrapper)
    manager = await CBManager.create(node_client, client_maker, cb_store)

    # setup for taker
    claim_db_path = tmp_path / "claim_clawback.db"
    claim_wrapper = await DBWrapper2.create(database=claim_db_path)
    claim_cb_store = await CBStore.create(claim_wrapper)
    claim_manager = await CBManager.create(node_client, client_taker, claim_cb_store)

    try:
        # Create a Clawback Coin
        spend_to_claw = await manager.create_cb_coin(amount, ph_taker, ph_maker, timelock, fee=fee)
        await node_client.push_tx(spend_to_claw)
        cb_coin = [coin for coin in spend_to_claw.additions() if coin.amount == amount][0]
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
        await manager.add_new_coin(cb_coin, ph_taker, ph_maker, timelock)
        records = await manager.get_cb_coins()
        assert len(records) == 1
        assert list(records)[0].coin == cb_coin

        # Try to claim before timelock
        early_claim = await claim_manager.create_claim_spend(cb_coin, ph_taker, fee)
        with pytest.raises(ValueError) as e_info:
            await node_client.push_tx(early_claim)
        assert "ASSERT_SECONDS_RELATIVE_FAILED" in e_info.value.args[0]["error"]

        # Claw it back
        cb_record = records.copy().pop()
        cb_spend = await manager.create_clawback_spend(cb_record, ph_maker, fee)
        await node_client.push_tx(cb_spend)
        cb_coin = [coin for coin in cb_spend.additions() if coin.amount == amount][0]
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
        new_coin = await node_client.get_coin_record_by_name(cb_coin.name())
        assert new_coin

        # Make another clawback coin
        short_timelock = 100
        spend_to_claim = await manager.create_cb_coin(amount, ph_taker, ph_maker, short_timelock, fee=fee)
        claim_coin = [coin for coin in spend_to_claim.additions() if coin.amount == amount][0]
        await node_client.push_tx(spend_to_claim)
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

        # Skip time 1
        full_node_api.use_current_time = False
        full_node_api.time_per_block = 60 * 60
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

        start_balance = await wallet_taker.get_confirmed_balance()
        claim_spend = await claim_manager.create_claim_spend(claim_coin, ph_taker, fee)
        await node_client.push_tx(claim_spend)
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
        end_balance = await wallet_taker.get_confirmed_balance()
        assert start_balance + amount - fee == end_balance

        # Create a clawback with multiple xch coins
        spendable_balance = await wallet_maker.get_confirmed_balance()
        coins = await wallet_maker.select_coins(spendable_balance)
        assert len(coins) > 1
        cb = await manager.create_cb_coin(spendable_balance, ph_taker, ph_maker, timelock, fee=0)
        res = await node_client.push_tx(cb)
        assert res["success"]

    finally:
        await cb_store.close()
        await claim_cb_store.close()
