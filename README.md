# Clawback Primitive

Clawbacks give you enhanced control over your transactions and ensure that you have an option to retrieve funds in the case of a fat finger error, or in cases where an attacker substitutes their address in place of a legitimate one. To create a clawback address, a timelock is specified by the sender along with the recipient's address and the sender's address. The funds are then sent to a coin which imposes the timelock on the recipient being able to claim the coins. The sender can spend the locked coin to recover the funds before the timelock passes, or before the recipient claims the coin.

Clawbacks use a `p2_1_of_n` puzzle which contains a merkle root of two puzzles: one for the sender to reclaim the coin (`p2_puzzle_hash`) and one for the recipient (`p2_augmented_condition`) which imposes the timelock. Spending the `p2_1_of_n` puzzle requires providing a proof and reveal of the puzzle you want to spend, and an appropriate solution to that puzzle.


## Setup

> **Note**
> This package requires a synced node and wallet.

1. Clone this repository
```shell
git clone https://github.com/Chia-Network/chia-clawback-primitive.git

```

2. Setup and activate a virtual environment
```shell
python3 -m venv venv
source venv/bin/activate
```

3. Install the clawback package and dependencies
```shell
pip install --extra-index-url https://pypi.chia.net/simple/ .
```
If you want to edit this repo install it with dev dependencies:
```shell
pip install --extra-index-url https://pypi.chia.net/simple/ -e .[dev]
```

4. Check it is installed correctly with:
```shell
clawback -h
```

The easiest way to test out this repo is with the simulator. It's recommended to run the sim in a separate venv as there are dependency issues between cdv and chia-blockchain@main. 

To setup the simulator, first create a new venv as per step 2 above, then:
```shell
pip install chia-dev-tools
cdv sim create
```

This will create and start a new sim. Then start a wallet:

```shell
chia start wallet
```

## CLI Documentation

### create
Sends a specified amount of xch from the connected wallet to a clawback coin with a given timelock

`clawback create`

`-t --to` Specify the xch address of the recipient
`-l --timelock` The timelock in seconds to use for the cb coin you're creating. Default is two weeks
`-a --amount` The amount in mojos to send from the wallet to the clawback
`-w --wallet-id` [Optional] The wallet id to fund the transaction from, currently only working/tested with xch coins
`-d --fee` [Optional] The fee for this transaction

### show
Get details for all outstanding clawback coins you've created

`clawback show`

`-c --coin-id` [Optional] specify a coin id to get clawback info for. This will also get the clawbback info even if you aren't the coin's creator. Output will be something like:

```shell
Coin ID: 5b74975e282ac2078f6418c58bc661ff71e0c5c03c8238f27f3a4f2aa03b384d
Amount: 100000000000 mojos
Timelock: 1000 seconds
Time left: 993 seconds
```

### clawback
Claw back an unclaimed coin

`clawback claw`

`-c --coin-id` The ID of the coin you want to claw back
`-t --target-address` The address where you want the clawback to be sent (can be any address). Defaults to the sender address used in creating the locked coin.
`-d --fee` [Optional] The fee for this transaction, funded from the connected xch wallet
`-w --wallet-id` [Optional] The wallet id to fund the transaction from

### claim
As the recipient of a clawback spend, this function will claim the coin to your address.

`clawback claim`

`-c --coin-id` The ID of the coin you want to claw back (only supports single use for now)
`-t --target-address` [Optional] The address where the funds will be send, defaults to the address recipient address used by the sender
`-d --fee` [Optional] The fee for this transaction, funded from the connected xch wallet
`-w --wallet-id` [Optional] The wallet id to fund the transaction from
