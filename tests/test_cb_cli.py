from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from src.cli.main import cli


def test_cli_get_address(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        address = runner.invoke(cli, ["get-address"])
        cb_coin = runner.invoke(cli, ["create-coin", "-a", "1000000", "-w", "1", "-f", "100"])
        cb_coins = runner.invoke(cli, ["get-my-coins"])
    assert address
    assert cb_coin
    assert cb_coins
