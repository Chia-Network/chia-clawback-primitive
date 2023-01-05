from __future__ import annotations

import time
from pathlib import Path
from secrets import token_bytes
from typing import List

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash
from click.testing import CliRunner

from src.cli.main import cli

# These tests require the external simulator and wallet
#
# cdv sim autofarm on
# chia start simulator
# chia start wallet


def test_cli_claw(tmp_path: Path) -> None:
    amount_1 = 1000
    amount_2 = 1000
    wallet_id = 1
    fee = 100
    target_address = encode_puzzle_hash(bytes32(token_bytes(32)), "xch")
    runner = CliRunner()
    with runner.isolated_filesystem():
        address = runner.invoke(cli, ["get_address"])
        cb_coin = runner.invoke(cli, ["create_coin", "-a", str(amount_1), "-w", str(wallet_id)])
        cb_coins = runner.invoke(cli, ["get_my_coins"])
        cb_tx = runner.invoke(cli, ["send_clawback", "-a", str(amount_2), "-t", target_address, "-d", str(fee)])
        created_coins = cb_tx.stdout.split("\n")[1:-1]
        id_opts: List[str] = []
        for cc in created_coins:
            id_opts = id_opts + ["-c", cc]
        claw_tx = runner.invoke(cli, ["clawback", "-t", target_address, *id_opts, "-d", str(fee)])
    assert address.exit_code == 0
    assert cb_coin.exit_code == 0
    assert cb_coins.exit_code == 0
    assert claw_tx.exit_code == 0


def test_cli_claim(tmp_path: Path) -> None:
    amount_1 = 10000
    amount_2 = 1000
    wallet_id = 1
    fee = 100
    target_address = encode_puzzle_hash(bytes32(token_bytes(32)), "xch")
    timelock = 5
    runner = CliRunner()
    with runner.isolated_filesystem():
        cb_coin = runner.invoke(
            cli, ["create_coin", "-l", str(timelock), "-a", str(amount_1), "-w", str(wallet_id), "-d", str(fee)]
        )
        cb_tx = runner.invoke(
            cli, ["send_clawback", "-l", str(timelock), "-a", str(amount_2), "-t", target_address, "-d", str(fee)]
        )
        time.sleep(10)
        # make another coin so we push another block
        cb_coin_2 = runner.invoke(cli, ["create_coin", "-a", str(amount_2), "-w", str(wallet_id), "-d", str(fee)])
        created_coins = cb_tx.stdout.split("\n")[1:-1]
        id_opts: List[str] = []
        for cc in created_coins:
            id_opts = id_opts + ["-c", cc]
        claim_tx = runner.invoke(cli, ["claim", "-t", target_address, *id_opts, "-d", str(fee)])
    assert cb_coin.exit_code == 0
    assert cb_coin_2.exit_code == 0
    assert claim_tx.exit_code == 0
