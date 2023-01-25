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


#### P2_MERKLE_ROOT
Coins controlled by clawback wallets have a wrapper puzzle that enforces the p2_merkle. The wallet also has to know a pubblic key for the cold-storage wallet, which it will use to create the clawback puzzlehash should the owner want to reclaim the coins.

Outline of a general puzzle for creating a merkle puzzle (not sure if we actually need this). It curries in a list of puzzles, and when spent it checks the create_coin conditions are spending to a merkle root of those puzzles with some curried params passed in the solution.

```
(mod
  (
    P2_MERKLE_ROOT_MOD
    PUZZLES
	curry_params
	conditions
  )
  
  (include merkle_utils.clib)
  
  (defmacro curry_params (puzzle params)
    ; pass each param into puzzle_hash_of_curried_function
  )
  
  (defun curry_puzzles (PUZZLES params)
	(if (r PUZZLES)
	  (c 
	     (curry_params (f PUZZLES) (f params))
		 (curry_puzzles (r PUZZLES) (r params))
	  )
	  (curry_params (f PUZZLES) (f params))
	)
  )
  
  (defun-inline check_condition (P2_MERKLE_ROOT_MOD PUZZLES params condition)
    (assert (= (f (r condition)) (calculate_merkle_root (curry_puzzles PUZZLES params)))
	  condition
	)
  )
  
  (defun validate_conditions (P2_MERKLE_ROOT_MOD PUZZLES params conditions)
    (if conditions
	  (c
		(if (= (f (f conditions)) CREATE_COIN)
		  (check_condition P2_MERKLE_ROOT_MOD PUZZLES params (f conditions))
		  (f conditions)
		)
		(validate_conditions P2_MERKLE_ROOT_MOD PUZZLES params (r conditions))
	  )
	  ()
	)
  )
  
  ; MAIN
  (validate_conditions P2_MERKLE_ROOT_MOD PUZZLES params conditions)
  
)
```



### Description of the clawback process
#### User creates a recoverable spend from a standard wallet
1. `A` takes a puzzle hash for the recipient's wallet `B`
2. creates the timelock condition `(ASSERT_SECONDS_RELATIVE t)` for some time `t`, and curries this along with `B`'s puzzle hash into the `augmented_condition` puzzle
3. creates the `p2_puzzlehash` puzzle by currying a puzzle hash from their own wallet (either hot wallet or cold wallet)
4. creates the `p2_merkle` puzzle by calculating the merkle root for the `augmented_condition` and `p2_puzzlehash` puzzles.
5. Create a spend from the wallet to the curried `p2_merkle` puzzle

#### If the user recovers the spend
1. `A` decides to reclaim the funds sent to the `p2_merkle` puzzle
2. Recreates the inner puzzle which is curried into `p2_puzzlehash`
3. Creates a solution to the inner puzzle to direct the funds to a puzzlehash of their choice (could be a cold wallet address or wherever)
4. Creates a merkle proof for spending the `p2_merkle` coin
5. Signs the spend bundle using the key which controls the curried puzzle hash (could be a different key from that used to create the spend in the first place)

#### If the recipient claims the spend
1. `B`'s wallet will need a way of discovering the `p2_merkle` coin via hint, and will also need a way to discover the timelock value `t`, and the puzzle hash used in `p2_puzzlehash` in order to create a proof for the merkle root. If `p2_merkle` is created from a wrapper puzzle, `B`'s wallet can the solution of the wrapper puzzle to get those values. If it's created directly from the standard wallet, the values will need to be passed in the hint/memos somehow.
2. Once `B` can calculate the merkle root and proof, they wait until the timelock has expired, then create a solution for the `augmented_condition` puzzle and claim the funds via the solution to the inner puzzle


