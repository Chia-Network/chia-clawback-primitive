# Clawback Primitive


The clawback primitive is intended to provide a basis for developers who want to use clawback functionality in their Chia tools and applications.

The clawback works by ensuring that xch secured with the clawback are sent to an intermediate coin which can only be claimed after a specified timelock has passed. Before the timelock has passed the original owner can claw back the funds to the original clawback puzzle.

The purpose of clawback is to make sure that if you send coins to the wrong address you can retrieve them. It does not protect you if someone gains access to your keys, because even though you can reverse the transactions they send, you can end up in a clawback stand-off where when you reverse transactions, the attacker keeps sending coins, potentially burning large fees in the process. Clawbacks give you enhanced control over your transactions and ensure that you have an option to retrieve funds in the case of a fat finger error, or in cases where an attacker substitutes their address in place of a legitimate one.


## Setup
** NOTE: This package requires a synced node and wallet. **

1. Clone this repository (and use validator branch for now)
```shell
git clone https://github.com/Chia-Network/chia-clawback-primitive.git
git checkout validator

```

2. Setup and activate a virtual environment
```shell
python3 -m venv venv
source venv/bin/activate
```

3. Install the clawback package and dependencies
```shell
pip install .[dev]
```

4. Check it is installed correctly with:
```shell
clawback -h
```



## CLI Documentation

### get-address
Returns an address which can be used to fund a clawback coin with a specified timelock

`clawback get-address`

`-l --timelock` The timelock in seconds to use for the cb coin you're creating. Default is two weeks

### create-coin
Sends a specified amount of xch from the connected wallet to a clawback coin with a given timelock

`clawback create-coin`

`-l --timelock` The timelock in seconds to use for the cb coin you're creating. Default is two weeks
`-a --amount` The amount in mojos to send from the wallet to the clawback
`-w --wallet-id` The wallet id to fund the transaction
`-d --fee` The fee for this transaction

### get-my-coins
Get details for all clawback coins for a given timelock

`clawback get-my-coins`
`-l --timelock` The timelock in seconds of the coins you want to look up. Default is two weeks

### send-clawback
Send an amount with a given timelock. The amount can be clawed back or claimed by the recipient after the timelock has passed

`clawback send-clawback`

`-l --timelock` The timelock for the coins you want to send
`-a --amount` The amount in mojos to send from the clawback
`-t --target-address` The recipient address
`-d --fee` The fee for this transaction, funded from the connected xch wallet

### clawback
Claw back a transaction which has been sent to a recipient (but not claimed)

`clawback clawback`

`-l --timelock` The timelock for the coins you want to send
`-t --target-address` The recipient's address used in the send-clawback transaction
`-c --coin-id` The ID of the coin you want to claw back (supports multiple use)
`-d --fee` The fee for this transaction, funded from the connected xch wallet

### claim
As the recipient of a clawback spend, this function will claim the coin to your address. It can be made by anyone  with connected node and wallet

`clawback claim`

`-t --target-address` The recipient's address used in the send-clawback transaction
`-c --coin-id` The ID of the coin you want to claw back (only supports single use for now)
`-d --fee` The fee for this transaction, funded from the connected xch wallet



## Some Technical Details
Clawback is enabled by the use of two main chialisp puzzles: A wrapper which holds the standard `p2_delgated_puzzle_or_hidden_puzzle`, and the intermediate puzzle where the balance is held until the coins are claimed or clawed back.

### Wrapper Puzzles
This is the puzzle that "locks" a balance in a coin and ensures that any spend can be clawed back. This uses the approach of meta-validator puzzles as outlined here: https://gist.github.com/richardkiss/43fc9add4e411880f58eaf387217b3f4#validation-driver

The validator puzzle: `validator.clsp` wraps the `p2_merkle_validator.clsp` puzzle. p2_merkle_validator is responsible for ensuring that any spend directs funds to either the intermediate puzzle, or back to the original clawback puzzle. It also provides an announcement of the amount to ensure that the full coin balance is accounted for.

### Intermediate Puzzle (p2_merkle)
The intermediate puzzle (p2\_merkle.clsp) is just a merkle root of two other puzzles: the clawback spend (ach\_clawback.clsp), and the claim spend (ach\_claim.clsp).

#### p2\_merkle.clsp
This is the intermediate puzzle where funds are held after they have been sent from the original owner. It can only be spent by providing the puzzle reveal and proof matching either the clawback or the claim puzzle with the necessary curried parameters. Because both the clawback and the claim puzzles will execute an inner puzzle the users must be able to provide the reveal of the inner puzzle and the appropriate signature. This ensures only the originator can spend the clawback and only the recipient can spend the claim puzzle.

#### ach_claim.clsp
This puzzle is used by the recipient to claim funds once the timelock has passed

#### ach_claw.clsp
This puzzle is used by the originator to claw back funds before timelock, or before the recipient has claimed the funds.


### Keys
This library uses the keys of the wallet client which is active while using the library. It creates a synthetic secret key with default index of 1 to create the inner puzzle of the clawback coins. The standard wallet is then able to sign these spends. Users should be aware of the potential privacy implications of re-using keys this way.


## Clawback as Protocol
Although this library uses the approach of locking coins so that they must always be spent to a clawback address, a more general-purpose approach would be for wallets to use clawback as a protocal, removing the need for the wrapper puzzle altogether. In this approach, when a user sends funds from their wallet to a recipient, they would have the option to provide a clawback timelock along with the other transaction details (amount, recipient address etc). The protocol would then curry together a p2_merkle puzzle and send the funds there, providing the user with details so they can claw back the transaction if needed.
