import asyncio
from typing import Optional

import click
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64

from src import __version__
from src.cb_utils import TWO_WEEKS
from src.clients import get_node_and_wallet_clients
from src.drivers.cb_manager import CBManager

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


def monkey_patch_click() -> None:
    import click.core

    click.core._verify_python3_env = lambda *args, **kwargs: 0  # type: ignore


@click.group(
    help="\n ClawBack Manager\n",
    context_settings=CONTEXT_SETTINGS,
)
@click.version_option(__version__)
@click.pass_context
def cli(ctx: click.Context) -> None:
    ctx.ensure_object(dict)


@cli.command(
    "get-address",
    short_help="Get a clawback address",
)
@click.option(
    "-t",
    "--timelock",
    help="The timelock to use for the cb coin you're creating. Default is two weeks",
    required=False,
    type=int,
    default=TWO_WEEKS,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    required=False,
    type=int,
    default=None,
)
@click.option(
    "-f",
    "--fingerprint",
    help="Set the fingerprint to specify which wallet to use",
    required=False,
    type=int,
    default=None,
)
@click.option(
    "-np",
    "--node-rpc-port",
    help="Set the port where the Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml",
    required=False,
    type=int,
    default=None,
)
def get_address_cmd(
    timelock: int,
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    Get a clawback address
    """

    async def do_command():
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)

        try:
            cb_manager = CBManager(node_client, wallet_client, timelock)
            await cb_manager.set_cb_info()
            res = await cb_manager.get_cb_address()
            print(res)
        finally:
            node_client.close()
            wallet_client.close()
            await node_client.await_closed()
            await wallet_client.await_closed()

    asyncio.get_event_loop().run_until_complete(do_command())


@cli.command(
    "create-coin",
    short_help="Send xch to a clawback coin",
)
@click.option(
    "-t",
    "--timelock",
    help="The timelock to use for the cb coin you're creating. Default is two weeks",
    required=False,
    type=int,
    default=TWO_WEEKS,
)
@click.option(
    "-a",
    "--amount",
    help="The amount to fund",
    required=True,
    type=int,
)
@click.option(
    "-w",
    "--wallet-id",
    help="The wallet id to fund from",
    required=True,
    type=int,
    default=1,
)
@click.option(
    "-f",
    "--fee",
    help="The fee for the funding transaction",
    required=False,
    type=int,
    default=0,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    required=False,
    type=int,
    default=None,
)
@click.option(
    "-f",
    "--fingerprint",
    help="Set the fingerprint to specify which wallet to use",
    required=False,
    type=int,
    default=None,
)
@click.option(
    "-np",
    "--node-rpc-port",
    help="Set the port where the Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml",
    required=False,
    type=int,
    default=None,
)
def create_cb_cmd(
    timelock: int,
    amount: int,
    wallet_id: int,
    fee: int = 0,
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    Create a transaction to fund a clawback coin
    """

    async def do_command():
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)

        try:
            cb_manager = CBManager(node_client, wallet_client, timelock)
            cb_info = await cb_manager.set_cb_info()
            additions = [{"puzzle_hash": cb_info.puzzle_hash(), "amount": amount}]
            tx = await wallet_client.create_signed_transaction(
                additions=additions, wallet_id=wallet_id, fee=uint64(fee)
            )
            assert isinstance(tx.spend_bundle, SpendBundle)
            res = await node_client.push_tx(tx.spend_bundle)
            assert res["success"]
            created_coin = [coin for coin in tx.spend_bundle.additions() if coin.amount == amount][0]
            print(res)
            print("Created Coin with ID: {}".format(created_coin.name().hex()))
            print(created_coin)
        finally:
            node_client.close()
            wallet_client.close()
            await node_client.await_closed()
            await wallet_client.await_closed()

    asyncio.get_event_loop().run_until_complete(do_command())


@cli.command(
    "get-my-coins",
    short_help="Get details for all clawback coins for a given timelock",
)
@click.option(
    "-t",
    "--timelock",
    help="The timelock to use for the cb coin you're creating. Default is two weeks",
    required=False,
    type=int,
    default=TWO_WEEKS,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    required=False,
    type=int,
    default=None,
)
@click.option(
    "-f",
    "--fingerprint",
    help="Set the fingerprint to specify which wallet to use",
    required=False,
    type=int,
    default=None,
)
@click.option(
    "-np",
    "--node-rpc-port",
    help="Set the port where the Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml",
    required=False,
    type=int,
    default=None,
)
def get_cb_coins_cmd(
    timelock: int,
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    Create a transaction to fund a clawback coin
    """

    async def do_command():
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)

        try:
            cb_manager = CBManager(node_client, wallet_client, timelock)
            await cb_manager.set_cb_info()
            coins = await cb_manager.get_cb_coins()
            total_amount = 0
            for coin_rec in coins:
                print("{}".format(coin_rec.coin))
                total_amount += coin_rec.coin.amount
            print("\nAvailable clawback balance: {} mojos".format(total_amount))
        finally:
            node_client.close()
            wallet_client.close()
            await node_client.await_closed()
            await wallet_client.await_closed()

    asyncio.get_event_loop().run_until_complete(do_command())


def main() -> None:
    monkey_patch_click()
    asyncio.run(cli())  # pylint: disable=no-value-for-parameter


if __name__ == "__main__":
    main()
