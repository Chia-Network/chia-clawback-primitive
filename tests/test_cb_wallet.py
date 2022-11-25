import pytest_asyncio
from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.rpc_server import start_rpc_server
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.setup_nodes import setup_simulators_and_wallets
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16


@pytest_asyncio.fixture(scope="function")
async def two_wallets():
    sims = setup_simulators_and_wallets(1, 2, {})
    async for _ in sims:
        yield _


@pytest_asyncio.fixture(scope="function")
async def maker_taker_rpc(two_wallets):
    full_nodes, wallets, bt = two_wallets
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server

    wallet_node_maker, server_0 = wallets[0]
    wallet_node_taker, server_1 = wallets[1]
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

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

    client_maker = await WalletRpcClient.create(self_hostname, rpc_server_maker.listen_port, bt.root_path, config)
    client_taker = await WalletRpcClient.create(self_hostname, rpc_server_taker.listen_port, bt.root_path, config)
    client_node = await FullNodeRpcClient.create(self_hostname, rpc_server_node.listen_port, bt.root_path, config)

    yield wallet_maker, client_maker, wallet_taker, client_taker, full_node_api, client_node,

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
