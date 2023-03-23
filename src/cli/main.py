import asyncio
import time
from pathlib import Path
from typing import Optional

import click
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash
from chia.util.db_wrapper import DBWrapper2

from src import __version__
from src.clients import get_node_and_wallet_clients
from src.drivers.cb_manager import TWO_WEEKS, CBManager
from src.drivers.cb_store import CBStore

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


def monkey_patch_click() -> None:
    import click.core

    click.core._verify_python3_env = lambda *args, **kwargs: 0  # type: ignore


def common_options(func):
    func = click.option(
        "-db",
        "--db-path",
        help="Set the path for the database",
        required=False,
        type=str,
        default="",
    )(func)
    func = click.option(
        "-wp",
        "--wallet-rpc-port",
        help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
        required=False,
        type=int,
        default=None,
    )(func)
    func = click.option(
        "-f",
        "--fingerprint",
        help="Set the fingerprint to specify which wallet to use",
        required=False,
        type=int,
        default=None,
    )(func)
    func = click.option(
        "-np",
        "--node-rpc-port",
        help="Set the port where the Node is hosting the RPC interface.",
        required=False,
        type=int,
        default=None,
    )(func)
    return func


@click.group(
    help="\n Clawback Primitive: Tooling to support clawbacks in Chia\n",
    context_settings=CONTEXT_SETTINGS,
)
@click.version_option(__version__)
@click.pass_context
def cli(ctx: click.Context) -> None:
    ctx.ensure_object(dict)


@cli.command(
    "create",
    short_help="Send xch to a clawback coin",
)
@click.option(
    "-t",
    "--to",
    help="The recipient's address",
    required=True,
    type=str,
)
@click.option(
    "-l",
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
    help="The wallet id to send from",
    required=False,
    type=int,
    default=1,
)
@click.option(
    "-d",
    "--fee",
    help="The fee for the funding transaction",
    required=False,
    type=int,
    default=0,
)
@common_options
def create_cmd(
    to: str,
    timelock: int,
    amount: int,
    wallet_id: int,
    fee: int = 0,
    db_path: str = "",
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    Make a transaction to create a clawback coin
    """

    async def do_command(fingerprint):
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)
        if not fingerprint:
            fingerprint = await wallet_client.get_logged_in_fingerprint()
        db_file = Path(db_path) / f"clawback_{fingerprint}.db"
        wrapper = await DBWrapper2.create(database=db_file)
        cb_store = await CBStore.create(wrapper)
        try:
            manager = await CBManager.create(node_client, wallet_client, cb_store)
            recipient_ph = decode_puzzle_hash(to)
            sender_addr = await wallet_client.get_next_address(wallet_id, True)
            sender_ph = decode_puzzle_hash(sender_addr)
            spend = await manager.create_cb_coin(amount, recipient_ph, sender_ph, timelock, fee=fee)
            await node_client.push_tx(spend)
            cb_coin = [coin for coin in spend.additions() if coin.amount == amount][0]
            await manager.add_new_coin(cb_coin, recipient_ph, sender_ph, timelock)
            print("Created Coin with ID: {}".format(cb_coin.name().hex()))
            print(cb_coin)
        finally:
            await cb_store.close()
            node_client.close()
            wallet_client.close()
            await node_client.await_closed()
            await wallet_client.await_closed()

    asyncio.get_event_loop().run_until_complete(do_command(fingerprint))


@cli.command(
    "show",
    short_help="Show details of all clawback coins",
)
@click.option(
    "-c",
    "--coin-id",
    help="The coin ID you want to claw back",
    required=False,
    type=str,
    default=None,
)
@common_options
def show_cmd(
    coin_id: str,
    db_path: str = "clawback.db",
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    Get details for all clawback coins
    """

    async def do_command(coin_id, fingerprint):
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)
        if not fingerprint:
            fingerprint = await wallet_client.get_logged_in_fingerprint()
        db_file = Path(db_path) / f"clawback_{fingerprint}.db"
        wrapper = await DBWrapper2.create(database=db_file)
        cb_store = await CBStore.create(wrapper)
        try:
            manager = await CBManager.create(node_client, wallet_client, cb_store)
            print("Updating coin records...")
            await manager.update_records()
            if coin_id:
                record = await manager.get_cb_info_by_id(bytes32.from_hexstr(coin_id))
                records = [record]
            else:
                records = await manager.get_cb_coins()
            current_time = time.time()
            if records:
                for record in records:
                    block = await node_client.get_block_record_by_height(record.confirmed_block_height)
                    time_left = int(record.timelock - (current_time - block.timestamp))
                    if time_left <= 0:
                        time_left = 0
                    print("\n")
                    print(f"Coin ID: {record.coin.name().hex()}")
                    print(f"Amount: {record.coin.amount} mojos")
                    print(f"Timelock: {record.timelock} seconds")
                    print(f"Time left: {time_left} seconds")
            else:
                print("No coins found")
        finally:
            await cb_store.close()
            node_client.close()
            wallet_client.close()
            await node_client.await_closed()
            await wallet_client.await_closed()

    asyncio.get_event_loop().run_until_complete(do_command(coin_id, fingerprint))


@cli.command(
    "claw",
    short_help="Clawback an unclaimed coin",
)
@click.option(
    "-c",
    "--coin-id",
    help="The coin ID you want to claw back",
    required=True,
    type=str,
)
@click.option(
    "-d",
    "--fee",
    help="The fee in mojos for this transaction",
    required=False,
    type=int,
    default=0,
)
@click.option(
    "-w",
    "--wallet-id",
    help="The wallet id for fees. If no target address given the clawback will go to this wallet id ",
    required=False,
    type=int,
    default=1,
)
@click.option(
    "-t",
    "--target-address",
    help="The address you want to sent the clawed back coin to",
    required=False,
    type=str,
    default=None,
)
@common_options
def claw_cmd(
    coin_id: str,
    fee: int = 0,
    wallet_id: int = 1,
    target_address: Optional[str] = None,
    db_path: str = "clawback.db",
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    Clawback an unclaimed coin
    """

    async def do_command(fee, wallet_id, target_address, fingerprint):
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)
        if not fingerprint:
            fingerprint = await wallet_client.get_logged_in_fingerprint()
        db_file = Path(db_path) / f"clawback_{fingerprint}.db"
        wrapper = await DBWrapper2.create(database=db_file)
        cb_store = await CBStore.create(wrapper)
        try:
            manager = await CBManager.create(node_client, wallet_client, cb_store)
            if not target_address:
                target_address = await wallet_client.get_next_address(wallet_id, True)
            target_ph = decode_puzzle_hash(target_address)
            cb_info = await manager.get_cb_info_by_id(bytes32.from_hexstr(coin_id))
            coin_record = await node_client.get_coin_record_by_name(bytes32.from_hexstr(coin_id))
            if coin_record.spent:
                raise ValueError("This coin has already been spent")
            spend = await manager.create_clawback_spend(cb_info, target_ph, fee)
            await node_client.push_tx(spend)
            print(f"Submitted spend to claw back coin: {coin_id}")
        finally:
            await cb_store.close()
            node_client.close()
            wallet_client.close()
            await node_client.await_closed()
            await wallet_client.await_closed()

    asyncio.get_event_loop().run_until_complete(do_command(fee, wallet_id, target_address, fingerprint))


@cli.command(
    "claim",
    short_help="Claim a clawback coin after the timelock has passed",
)
@click.option(
    "-c",
    "--coin-id",
    help="The coin ID you want to claim",
    required=True,
    type=str,
)
@click.option(
    "-d",
    "--fee",
    help="The fee in mojos for this transaction",
    required=False,
    type=int,
    default=0,
)
@click.option(
    "-w",
    "--wallet-id",
    help="The wallet id for fees. If no target address given the clawback will go to this wallet id ",
    required=False,
    type=int,
    default=1,
)
@click.option(
    "-t", "--target-address", help="The address you want to send the coin to", required=False, type=str, default=None
)
@common_options
def claim_cmd(
    coin_id: str,
    fee: int = 0,
    wallet_id: int = 1,
    target_address: Optional[str] = None,
    db_path: str = "clawback.db",
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    Clawback an unclaimed coin
    """

    async def do_command(fee, wallet_id, target_address, fingerprint):
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)
        if not fingerprint:
            fingerprint = await wallet_client.get_logged_in_fingerprint()
        db_file = Path(db_path) / f"clawback_{fingerprint}.db"
        wrapper = await DBWrapper2.create(database=db_file)
        cb_store = await CBStore.create(wrapper)
        try:
            manager = await CBManager.create(node_client, wallet_client, cb_store)
            if not target_address:
                target_address = await wallet_client.get_next_address(wallet_id, True)
            target_ph = decode_puzzle_hash(target_address)
            coin_record = await node_client.get_coin_record_by_name(bytes32.from_hexstr(coin_id))
            if coin_record.spent:
                raise ValueError("This coin has already been spent")
            spend = await manager.create_claim_spend(coin_record.coin, target_ph, fee)
            await node_client.push_tx(spend)
            print(f"Submitted spend to claim coin: {coin_id}")
        finally:
            await cb_store.close()
            node_client.close()
            wallet_client.close()
            await node_client.await_closed()
            await wallet_client.await_closed()

    asyncio.get_event_loop().run_until_complete(do_command(fee, wallet_id, target_address, fingerprint))


def main() -> None:
    monkey_patch_click()
    asyncio.run(cli())  # pylint: disable=no-value-for-parameter


if __name__ == "__main__":
    main()
