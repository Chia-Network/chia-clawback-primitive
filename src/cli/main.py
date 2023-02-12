import asyncio
from typing import List, Optional

import click
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import decode_puzzle_hash
from chia.util.ints import uint64

from src import __version__
from src.clients import get_node_and_wallet_clients
from src.drivers.cb_puzzles import TWO_WEEKS
from src.drivers.cb_manager import CBManager

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


def monkey_patch_click() -> None:
    import click.core

    click.core._verify_python3_env = lambda *args, **kwargs: 0  # type: ignore

def common_options(func):
    func = click.option(
        "-k",
        "--key-index",
        help="The key derivation index (default 1)",
        required=False,
        type=int,
        default=1,
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
        help="Set the port where the Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml",
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
    "get_address",
    short_help="Get a clawback address",
)
@click.option(
    "-t",
    "--to-address",
    help="The recipient's address"
    required=True,
    type=str,
)
@click.option(
    "-l",
    "--timelock",
    help="The timelock to use for the clawback coin you're creating. Default is two weeks",
    required=False,
    type=int,
    default=TWO_WEEKS,
)
@common_options
def get_address_cmd(
    to_address: str,
    timelock: int,
    key_index: int,
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    Get a clawback address from the connected wallet client
    """

    async def do_command():
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)
        recipient_ph = decode_puzzle_hash(to_address)
        try:
            cb_manager = CBManager(node_client, wallet_client, key_index)
            res = await cb_manager.get_cb_address(timelock, recipient_ph, prefix)
            print(res)
        finally:
            node_client.close()
            wallet_client.close()
            await node_client.await_closed()
            await wallet_client.await_closed()

    asyncio.get_event_loop().run_until_complete(do_command())


@cli.command(
    "create_coin",
    short_help="Send xch to a clawback coin",
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
    help="The wallet id to fund from",
    required=True,
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
            cb_manager = CBManager(node_client, wallet_client)
            cb_info = await cb_manager.set_cb_info(timelock)
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
    "get_my_coins",
    short_help="Get details for all clawback coins for a given timelock",
)
@click.option(
    "-l",
    "--timelock",
    help="The timelock to use for the cb coin you're creating. Default is two weeks",
    required=False,
    type=int,
    default=TWO_WEEKS,
)
@common_options
def get_cb_coins_cmd(
    timelock: int,
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    Get details for all clawback coins for a given timelock
    """

    async def do_command():
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)

        try:
            cb_manager = CBManager(node_client, wallet_client)
            await cb_manager.set_cb_info(timelock)
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


@cli.command("send_clawback", short_help="Send a clawback transaction")
@click.option(
    "-l",
    "--timelock",
    help="The timelock on the coin(s) you want to spend. Default is two weeks",
    required=False,
    type=int,
    default=TWO_WEEKS,
)
@click.option(
    "-a",
    "--amount",
    help="The amount (in mojos) to send",
    required=True,
    type=int,
)
@click.option(
    "-t",
    "--target-address",
    help="The target address of the clawback",
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
@common_options
def send_clawback_cmd(
    timelock: int,
    amount: int,
    target_address: str,
    fee: int,
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    Send a clawback transaction to the intermediate puzzle
    """

    async def do_command():
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)

        try:
            cb_manager = CBManager(node_client, wallet_client)
            cb_info = await cb_manager.set_cb_info(timelock)
            target_puzzle_hash = decode_puzzle_hash(target_address)
            cb_spend = await cb_manager.send_cb_coin(amount, target_puzzle_hash, fee)
            res = await node_client.push_tx(cb_spend)
            assert res["success"]
            p2_merkle_coins = [coin for coin in cb_spend.additions() if coin.puzzle_hash != cb_info.puzzle_hash()]
            print("Created coin ids:")
            for coin in p2_merkle_coins:
                print("{}".format(coin.name().hex()))

        finally:
            node_client.close()
            wallet_client.close()
            await node_client.await_closed()
            await wallet_client.await_closed()

    asyncio.get_event_loop().run_until_complete(do_command())


@cli.command(
    "clawback",
    short_help="Clawback a previously sent transaction",
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
    "-t",
    "--target-address",
    help="The original target address you sent the clawback to",
    required=True,
    type=str,
)
@click.option(
    "-c",
    "--coin-ids",
    help="The coin IDs you want to claw back (supports multiple use)",
    required=True,
    multiple=True,
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
@common_options
def clawback_coin_cmd(
    timelock: int,
    target_address: str,
    coin_ids: List[str],
    fee: int,
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    Clawback a transaction
    """

    async def do_command():
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)

        try:
            cb_manager = CBManager(node_client, wallet_client)
            await cb_manager.set_cb_info(timelock)
            coin_id_bytes = [bytes32.from_hexstr(coin_id) for coin_id in coin_ids]
            target_puzzle_hash = decode_puzzle_hash(target_address)
            cb_spend = await cb_manager.clawback_p2_merkle_coin_ids(coin_id_bytes, target_puzzle_hash, fee)
            res = await node_client.push_tx(cb_spend)
            assert res["success"]
            print("Successfully clawed back coin(s): {}".format(coin_ids))

        finally:
            node_client.close()
            wallet_client.close()
            await node_client.await_closed()
            await wallet_client.await_closed()

    asyncio.get_event_loop().run_until_complete(do_command())


@cli.command(
    "claim",
    short_help="Claim a balance after the timelock has passed",
)
@click.option(
    "-t",
    "--target-address",
    help="The original target address of the clawback",
    required=True,
    type=str,
)
@click.option(
    "-c",
    "--coin-ids",
    help="The coin ID you want to claim (supports multiple)",
    required=True,
    multiple=True,
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
    help="The wallet id to fund the fee spend from",
    required=False,
    type=int,
    default=1,
)
@common_options
def claim_coin_cmd(
    target_address: str,
    coin_ids: List[str],
    fee: int = 0,
    wallet_id: int = 1,
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    Claim an intermediate coin after the timelock has passed
    """

    async def do_command():
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)

        try:
            cb_manager = CBManager(node_client, wallet_client)
            target_puzzle_hash = decode_puzzle_hash(target_address)
            coin_id_bytes = [bytes32.from_hexstr(coin_id) for coin_id in coin_ids]
            cb_spend = await cb_manager.claim_p2_merkle_multiple(coin_id_bytes, target_puzzle_hash, fee, fee_wallet_id=wallet_id)
            # if fee > 0:
            #     fee_spend = await cb_manager.create_fee_spend(fee, announcements)
            #     sb = SpendBundle.aggregate([cb_spend, fee_spend])
            # else:
            #     sb = cb_spend
            res = await node_client.push_tx(cb_spend)
            assert res["success"]
            print("Successfully claimed coins: {}".format(coin_ids))

        finally:
            node_client.close()
            wallet_client.close()
            await node_client.await_closed()
            await wallet_client.await_closed()

    asyncio.get_event_loop().run_until_complete(do_command())

@cli.command(
    "send_direct",
    short_help="Claim a balance after the timelock has passed",
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
    help="The amount (in mojos) to send",
    required=True,
    type=int,
)
@click.option(
    "-t",
    "--target-address",
    help="The original target address of the clawback",
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
@common_options
def send_direct_cmd(
    timelock: int,
    amount: int,
    target_address: str,
    fee: int,
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    Claim an intermediate coin after the timelock has passed
    """

    async def do_command():
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)

        try:
            cb_manager = CBManager(node_client, wallet_client)
            cb_info = cb_manager.set_cb_info(timelock)
            
            target_puzzle_hash = decode_puzzle_hash(target_address)
            coin_id_bytes = bytes32.from_hexstr(coin_id)
            cb_spend = await cb_manager.claim_p2_merkle(coin_id_bytes, target_puzzle_hash)
            if fee > 0:
                fee_spend = await cb_manager.create_fee_spend(fee)
                sb = SpendBundle.aggregate([cb_spend, fee_spend])
            else:
                sb = cb_spend
            res = await node_client.push_tx(sb)
            assert res["success"]
            print("Successfully claimed coin: {}".format(coin_id))

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
