from __future__ import annotations

import asyncio
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
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint16, uint64
from chia.wallet.wallet import Wallet

from src.cb_utils import TEN_SECONDS, TWO_WEEKS
from src.drivers.cb_manager import CBManager


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

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

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
async def test_cb_clawback(
    tmp_path: Path,
    maker_taker_rpc: Tuple[Wallet, WalletRpcClient, Wallet, WalletRpcClient, FullNodeSimulator, FullNodeRpcClient],
) -> None:
    wallet_maker, client_maker, wallet_taker, client_taker, full_node_api, node_client = maker_taker_rpc
    wallet_id = 1
    amount = uint64(100000000)
    timelock = TWO_WEEKS
    manager = CBManager(node_client, client_maker)
    ph_token = bytes32(token_bytes(32))
    fee = uint64(10)

    # Create a Clawback Coin
    cb_info = await manager.set_cb_info(timelock)

    additions = [{"puzzle_hash": cb_info.puzzle_hash(), "amount": amount}]
    tx = await client_maker.create_signed_transaction(additions=additions, wallet_id=wallet_id)
    assert isinstance(tx.spend_bundle, SpendBundle)
    await node_client.push_tx(tx.spend_bundle)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    cb_coin: Coin = (await manager.get_cb_coins())[0].coin
    assert cb_coin.puzzle_hash == cb_info.puzzle_hash()

    # send the cb coin to p2_merkle
    taker_ph = await wallet_taker.get_new_puzzlehash()
    p2_merkle_sb = await manager.send_cb_coin(amount, taker_ph, fee)
    await node_client.push_tx(p2_merkle_sb)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    merkle_coin = (await manager.get_p2_merkle_coins(taker_ph))[0]

    # clawback the p2_merkle
    claw_sb = await manager.clawback_p2_merkle([merkle_coin], taker_ph, fee)
    # check we don't have a cb coin:
    cb_coins = await manager.get_cb_coins()
    assert not cb_coins

    # push the spend and check we have a returned cb coin
    await node_client.push_tx(claw_sb)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    cb_coins = await manager.get_cb_coins()
    assert len(cb_coins) == 1
    assert cb_coins[0].coin.amount == amount - (2 * fee)


@pytest.mark.asyncio
async def test_cb_claim(
    tmp_path: Path,
    maker_taker_rpc: Tuple[Wallet, WalletRpcClient, Wallet, WalletRpcClient, FullNodeSimulator, FullNodeRpcClient],
) -> None:
    wallet_maker, client_maker, wallet_taker, client_taker, full_node_api, node_client = maker_taker_rpc
    wallet_id = 1
    amount = uint64(100000000)
    timelock = TEN_SECONDS
    manager = CBManager(node_client, client_maker)
    ph_token = bytes32(token_bytes(32))
    fee = uint64(10)

    # Create a Clawback Coin
    cb_info = await manager.set_cb_info(timelock)

    additions = [{"puzzle_hash": cb_info.puzzle_hash(), "amount": amount}]
    tx = await client_maker.create_signed_transaction(additions=additions, wallet_id=wallet_id)
    assert isinstance(tx.spend_bundle, SpendBundle)
    await node_client.push_tx(tx.spend_bundle)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    cb_coin: Coin = (await manager.get_cb_coins())[0].coin
    assert cb_coin.puzzle_hash == cb_info.puzzle_hash()

    # send the cb coin to p2_merkle
    taker_ph = await wallet_taker.get_new_puzzlehash()
    p2_merkle_sb = await manager.send_cb_coin(amount, taker_ph, fee)
    await node_client.push_tx(p2_merkle_sb)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    merkle_coin = (await manager.get_p2_merkle_coins(taker_ph))[0]

    # claim the p2_merkle too early
    claim_sb = await manager.claim_p2_merkle(merkle_coin.name(), taker_ph, fee)
    with pytest.raises(ValueError) as e_info:
        await node_client.push_tx(claim_sb)

    assert "ASSERT_SECONDS_RELATIVE_FAILED" in e_info.value.args[0]["error"]

    # wait and claim it after timelock
    # TODO: Force block timestamps to avoid using asyncio.sleep
    await asyncio.sleep(20)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    await node_client.push_tx(claim_sb)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    taker_coins = await node_client.get_coin_records_by_puzzle_hash(taker_ph, include_spent_coins=False)
    assert len(taker_coins) == 1
    assert taker_coins[0].coin.amount == amount - (2 * fee)


@pytest.mark.asyncio
async def test_cb_multiple_coins(
    tmp_path: Path,
    maker_taker_rpc: Tuple[Wallet, WalletRpcClient, Wallet, WalletRpcClient, FullNodeSimulator, FullNodeRpcClient],
) -> None:
    wallet_maker, client_maker, wallet_taker, client_taker, full_node_api, node_client = maker_taker_rpc
    wallet_id = 1
    amount_1 = uint64(500000)
    amount_2 = uint64(500)
    fee = uint64(1000)
    send_amount = uint64(499400)
    timelock = TWO_WEEKS
    manager = CBManager(node_client, client_maker)
    ph_token = bytes32(token_bytes(32))

    # Create a Clawback Coin
    cb_info = await manager.set_cb_info(timelock)

    # First Coin
    additions = [{"puzzle_hash": cb_info.puzzle_hash(), "amount": amount_1}]
    tx = await client_maker.create_signed_transaction(additions=additions, wallet_id=wallet_id)
    assert isinstance(tx.spend_bundle, SpendBundle)
    await node_client.push_tx(tx.spend_bundle)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    # Second coin
    additions = [{"puzzle_hash": cb_info.puzzle_hash(), "amount": amount_2}]
    tx = await client_maker.create_signed_transaction(additions=additions, wallet_id=wallet_id)
    assert isinstance(tx.spend_bundle, SpendBundle)
    await node_client.push_tx(tx.spend_bundle)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    # send 2 cb coins to p2_merkle
    taker_ph = await wallet_taker.get_new_puzzlehash()
    p2_merkle_sb = await manager.send_cb_coin(send_amount, taker_ph, fee)

    await node_client.push_tx(p2_merkle_sb)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    merkle_coins = await manager.get_p2_merkle_coins(taker_ph)
    assert sum([coin.amount for coin in merkle_coins]) == send_amount

    # check the change coin exists:
    cb_coins = await manager.get_cb_coins()
    assert len(cb_coins) == 1
    cb_amount_left = amount_1 + amount_2 - send_amount - fee
    assert cb_coins[0].coin.amount == cb_amount_left

    # clawback the p2_merkle coins
    claw_sb = await manager.clawback_p2_merkle(merkle_coins, taker_ph, fee)
    # breakpoint()

    # push the spend and check we have a returned cb coin
    await node_client.push_tx(claw_sb)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    cb_coins = await manager.get_cb_coins()
    assert sum([cr.coin.amount for cr in cb_coins]) == send_amount - fee + cb_amount_left
