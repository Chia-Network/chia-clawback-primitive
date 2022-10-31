# Clawback Primitive


The clawback primitive is intended to provide a basis for developers who want to use clawback functionality in their Chia tools and applications.

In brief, the clawback works by ensuring that xch secured with the clawback are sent to an intermediate address. The address which is receiving the funds can only claim them once a certain time has passed. The length of the time lock is decided by the original owner when they are setting up the clawback for their funds. If the user wishes to clawback their funds, they can so until the timelock has elapsed.

To be slightly more technical, the intermediate puzzle is a merkle tree of two puzzles: the curried clawback and the curried claim puzzles. To execute this puzzle the user must prove knowledge of the puzzle and their curried parameters. Each party is only able to prove one of the two puzzles, and the time lock conditions are enforced only by the claim puzzle. This means that if the timelock has elapsed but the recipient has not claimed the coins, the sender can still run the clawback puzzle.


## Chialisp
There are several puzzles which work together to enable clawbacks.

### cb\_outer.clsp
This is an outer puzzle which wraps the standard transaction (p2\_delegated\_or\_hidden\_puzzle). It's main responsibility is to police the `CREATE_COIN` conditions from the inner puzzle, and ensure that any amounts are sent to the intermediate puzzle, `p2_merkle.clsp`.

### p2\_merkle.clsp
This is the intermediate puzzle where funds are held after they have been sent from the original owner. It can only be spent by providing the puzzle reveal and proof matching either the clawback or the claim puzzle with the necessary curried parameters. Because both the clawback and the claim puzzles will execute an inner puzzle the users must be able to provide the reveal of the inner puzzle and the appropriate signature. This ensures only the originator can spend the clawback and only the recipient can spend the claim puzzle.

### ach_claim.clsp
This puzzle is used by the recipient to claim funds once the timelock has passed

### ach_claw.clsp
This puzzle is used by the originator to claw back funds before timelock, or before the recipient has claimed the funds.
