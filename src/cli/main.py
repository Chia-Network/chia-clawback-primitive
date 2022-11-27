import asyncio
from typing import Optional

import click

from clients import get_node_and_wallet_clients

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


def monkey_patch_click() -> None:
    import click.core

    click.core._verify_python3_env = lambda *args, **kwargs: 0  # type: ignore


@click.group(
    help="\n ClawBack Wallet \n",
    context_settings=CONTEXT_SETTINGS,
)
# @click.version_option(__version__)
@click.pass_context
def cli(ctx: click.Context) -> None:
    ctx.ensure_object(dict)


@cli.command(
    "create",
    short_help="Create a set of spend bundles for minting NFTs",
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option(
    "-f",
    "--fingerprint",
    help="Set the fingerprint to specify which wallet to use",
    type=int,
    default=None,
)
@click.option(
    "-np",
    "--node-rpc-port",
    help="Set the port where the Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml",
    type=int,
    default=None,
)
def create_spend_bundles_cmd(
    wallet_rpc_port: Optional[int] = None,
    fingerprint: Optional[int] = None,
    node_rpc_port: Optional[int] = None,
):
    """
    \b
    CREATE a clawback wallet
    """

    async def do_command():
        node_client, wallet_client = await get_node_and_wallet_clients(node_rpc_port, wallet_rpc_port, fingerprint)

        try:
            print("Creating clawback wallet")
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
