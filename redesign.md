## Clawback Technical Design

### Puzzles

#### P2_MERKLE
This general puzzle curries a merkle root of n puzzles. The solver provides a proof, and the puzzle reveal which matches the puzzle they want to exectute. If succesfully proved/validated then the leaf puzzle and its solution is executed.

```
(mod
  (
    MERKLE_ROOT
    puzzle_to_execute
    merkle_proof
    inner_solution
  )

  (include merkle_utils.clib)

  (assert (= MERKLE_ROOT (simplify_merkle_proof (sha256tree puzzle_to_execute) merkle_proof))
    (a puzzle_to_execute inner_solution)
  )
)

```

#### AUGMENTED_CONDITION
This takes a curried puzzle hash of an inner puzzle, and a condition. If the solver provides the matching puzzle reveal with a solution, the curried condition is appended to the output of the inner puzzle/solution

```
(mod
  (
    CONDITION
    INNER_PUZZLE_HASH
    inner_puzzle
    inner_solution
  )

  (if (= (sha256tree inner_puzzle) INNER_PUZZLE_HASH)
    (c
      CONDITION
      (a inner_puzzle inner_solution)
    )
  )
)
```

Question: Is it preferable to take a list of conditions?

#### CLAWBACK
This is just a p2_puzzle_hash where the curried puzhash is dictated by the type of wallet creating the spend. For security wallets, the puzzlehash is for the cold-wallet. For fat-finger prevention it can just be a standard wallet puzzle hash.

```
(mod
  (
    PUZZLE_HASH
    puzzle
    solution
    my_amount
  )

  (if (= (sha256tree inner_puzzle) PUZZLE_HASH)
    (c
      (CREATE_COIN PUZZLE_HASH my_amount)
      (c
        (ASSERT_MY_AMOUNT my_amount)
        (a puzzle solution)
      )
    )
  )
)
```


#### WALLET_WRAPPER
Coins controlled by clawback wallets have a wrapper puzzle that enforces the p2_merkle. The wallet also has to know a pubblic key for the cold-storage wallet, which it will use to create the clawback puzzlehash should the owner want to reclaim the coins.

