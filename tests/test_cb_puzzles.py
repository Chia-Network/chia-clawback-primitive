from blspy import G1Element
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet.nft_puzzles import NFT_METADATA_UPDATER, create_full_puzzle
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import solution_for_conditions
from clvm.casts import int_to_bytes

from src.drivers.cb_puzzles import (
    ClawbackInfo,
    construct_p2_merkle_puzzle,
    solve_cb_outer_puzzle,
    solve_p2_merkle_claim,
    solve_p2_merkle_claw,
)
from src.load_clvm import load_clvm

CB_MOD = load_clvm("cb_outer.clsp", package_or_requirement="src.clsp")
CB_MOD_HASH = CB_MOD.get_tree_hash()
P2_MERKLE_MOD = load_clvm("p2_merkle_tree.clsp", package_or_requirement="src.clsp")
P2_MERKLE_MOD_HASH = P2_MERKLE_MOD.get_tree_hash()
ACH_COMPLETION_MOD = load_clvm("ach_completion.clsp", package_or_requirement="src.clsp")
ACH_COMPLETION_MOD_HASH = ACH_COMPLETION_MOD.get_tree_hash()
ACH_CLAWBACK_MOD = load_clvm("ach_clawback.clsp", package_or_requirement="src.clsp")
ACH_CLAWBACK_MOD_HASH = ACH_CLAWBACK_MOD.get_tree_hash()
ACS = Program.to(1)
ACS_PH = ACS.get_tree_hash()

VALIDATOR_MOD = load_clvm("validator.clsp", package_or_requirement="src.clsp")
VALIDATOR_MOD_HASH = VALIDATOR_MOD.get_tree_hash()
P2_MERKLE_VALIDATOR_MOD = load_clvm("p2_merkle_validator.clsp", package_or_requirement="src.clsp")


def test_p2_merkle_validator():
    TIMELOCK = 600
    pubkey = G1Element()
    cb_info = ClawbackInfo(TIMELOCK, pubkey)
    p2_merkle_ph = construct_p2_merkle_puzzle(cb_info, ACS_PH).get_tree_hash()

    CURRIED_DATA = [
        VALIDATOR_MOD_HASH,
        P2_MERKLE_VALIDATOR_MOD,
        ACH_CLAWBACK_MOD_HASH,
        ACH_COMPLETION_MOD_HASH,
        P2_MERKLE_MOD_HASH,
        TIMELOCK,
        cb_info.inner_puzzle,
    ]

    p2_merkle_validator = P2_MERKLE_VALIDATOR_MOD.curry(CURRIED_DATA)

    puzzle_list = [[P2_MERKLE_VALIDATOR_MOD, CURRIED_DATA], [cb_info.inner_puzzle, []]]
    puzzle_and_curry_params = Program.to(puzzle_list)
    validator_puzzle = VALIDATOR_MOD.curry(puzzle_and_curry_params)

    p2_merkle_conds = [
        [51, p2_merkle_ph, 100],
        [73, 800],
        [51, p2_merkle_ph, 300],
        [51, validator_puzzle.get_tree_hash(), 400],
    ]
    solution_data = [ACS_PH, ACS_PH, cb_info.inner_puzzle.get_tree_hash()]

    result: Program = p2_merkle_validator.run(Program.to([solution_data, p2_merkle_conds]))
    assert result.as_int() == 1


def test_validator():
    TIMELOCK = 600
    pubkey = G1Element()
    cb_info = ClawbackInfo(TIMELOCK, pubkey)
    target_ph = ACS_PH
    p2_merkle_ph = construct_p2_merkle_puzzle(cb_info, target_ph).get_tree_hash()

    CURRIED_DATA = [
        VALIDATOR_MOD_HASH,
        P2_MERKLE_VALIDATOR_MOD,
        ACH_CLAWBACK_MOD_HASH,
        ACH_COMPLETION_MOD_HASH,
        P2_MERKLE_MOD_HASH,
        TIMELOCK,
        cb_info.inner_puzzle,
    ]

    puzzle_list = [[P2_MERKLE_VALIDATOR_MOD, CURRIED_DATA], [cb_info.inner_puzzle, []]]
    puzzle_and_curry_params = Program.to(puzzle_list)
    validator_puzzle = VALIDATOR_MOD.curry(puzzle_and_curry_params)

    # p2_merkle_conds = [[51, p2_merkle_ph, 100], [73, 100]]
    p2_merkle_conds = [
        [51, p2_merkle_ph, 100],
        [51, p2_merkle_ph, 300],
        [73, 400],
    ]
    solution_data = [ACS_PH, ACS_PH]

    inner_sol = solution_for_conditions(p2_merkle_conds)

    validator_sol = Program.to([[solution_data, inner_sol]])

    conds = validator_puzzle.run(validator_sol)
    cds = conds.as_python()
    assert len(cds) == len(p2_merkle_conds) + 1


def test_clawback_xch():
    TIMELOCK = 100
    pubkey = G1Element()
    cb_info = ClawbackInfo(TIMELOCK, pubkey)
    amt_1 = 200
    amt_2 = 800
    primaries = [{"puzzle_hash": ACS_PH, "amount": amt_1}, {"puzzle_hash": ACS_PH, "amount": amt_2}]

    cb_puz = cb_info.outer_puzzle()
    cb_sol = solve_cb_outer_puzzle(cb_info, primaries)

    cb_conds = cb_puz.run(cb_sol).as_python()

    merkle_puz = construct_p2_merkle_puzzle(cb_info, ACS_PH)
    merkle_ph = merkle_puz.get_tree_hash()

    expected_conds = [
        [b"3", merkle_ph, int_to_bytes(amt_1)],
        [b"3", merkle_ph, int_to_bytes(amt_2)],
        [b"I", int_to_bytes(amt_1 + amt_2)],
    ]

    for cond in expected_conds:
        assert cond in cb_conds

    # Create claim and clawback solutions
    claw_primary = {"puzzle_hash": cb_info.outer_puzzle().get_tree_hash(), "amount": amt_1}
    claw_sol = solve_p2_merkle_claw(cb_info, claw_primary, ACS_PH)
    claim_sol = solve_p2_merkle_claim(cb_info, amt_2, ACS_PH)

    # Run clawback
    claw_merkle_conds = merkle_puz.run(claw_sol)
    expected_conds = [[b"3", cb_puz.get_tree_hash(), int_to_bytes(amt_1)], [b"I", int_to_bytes(amt_1)]]
    for cond in expected_conds:
        assert cond in claw_merkle_conds.as_python()

    # Run claim
    claim_merkle_conds = merkle_puz.run(claim_sol)
    expected_cond = [b"3", ACS_PH, int_to_bytes(amt_2)]
    assert expected_cond in claim_merkle_conds.as_python()


def test_clawback_cat():

    amount = uint64(10000)
    TIMELOCK = 100
    pubkey = G1Element()
    cb_info = ClawbackInfo(TIMELOCK, pubkey)
    primaries = [{"puzzle_hash": ACS_PH, "amount": amount}]

    cb_puz = cb_info.outer_puzzle()
    cb_sol = solve_cb_outer_puzzle(cb_info, primaries)

    merkle_puz = construct_p2_merkle_puzzle(cb_info, ACS_PH)

    # Set up a Clawback CAT
    tail = Program.to("tail").get_tree_hash()
    cat_puz = CAT_MOD.curry(CAT_MOD.get_tree_hash(), tail, cb_puz)

    parent_parent_id = Program.to("parent_id").get_tree_hash()
    parent_coin = Coin(parent_parent_id, cat_puz.get_tree_hash(), amount)
    lineage_proof = LineageProof(parent_parent_id, cb_puz.get_tree_hash(), amount)
    parent_id = parent_coin.name()

    prev_coin_id = Program.to("prev_coin_id").get_tree_hash()
    this_coin_info = [parent_id, cat_puz.get_tree_hash(), amount]
    next_coin_proof = [parent_id, cb_puz.get_tree_hash(), amount]
    prev_subtotal = 100
    extra_delta = 0

    cat_sol = Program.to(
        [
            cb_sol,
            lineage_proof.to_program(),
            prev_coin_id,
            this_coin_info,
            next_coin_proof,
            prev_subtotal,
            extra_delta,
        ]
    )

    conds = cat_puz.run(cat_sol)
    new_ph = bytes32([cond[1] for cond in conds.as_python() if cond[0] == b"3"][0])
    merkle_cat = CAT_MOD.curry(CAT_MOD.get_tree_hash(), tail, merkle_puz)
    assert new_ph == merkle_cat.get_tree_hash()

    claw_primary = {"puzzle_hash": cb_puz.get_tree_hash(), "amount": 1000}
    claw_sol = solve_p2_merkle_claw(cb_info, claw_primary, ACS_PH)
    claim_sol = solve_p2_merkle_claim(cb_info, 1000, ACS_PH)

    merkle_cat_claw_sol = Program.to(
        [
            claw_sol,
            lineage_proof.to_program(),
            prev_coin_id,
            this_coin_info,
            next_coin_proof,
            prev_subtotal,
            extra_delta,
        ]
    )

    merkle_cat_claim_sol = Program.to(
        [
            claim_sol,
            lineage_proof.to_program(),
            prev_coin_id,
            this_coin_info,
            next_coin_proof,
            prev_subtotal,
            extra_delta,
        ]
    )

    claw_conds = merkle_cat.run(merkle_cat_claw_sol)
    clawed_ph = bytes32([cond[1] for cond in claw_conds.as_python() if cond[0] == b"3"][0])
    assert clawed_ph == cat_puz.get_tree_hash()

    claim_conds = merkle_cat.run(merkle_cat_claim_sol)
    claimed_ph = bytes32([cond[1] for cond in claim_conds.as_python() if cond[0] == b"3"][0])
    claimed_cat = CAT_MOD.curry(CAT_MOD.get_tree_hash(), tail, ACS)
    assert claimed_ph == claimed_cat.get_tree_hash()


def test_clawback_nft():
    amount = uint64(1)
    TIMELOCK = 100
    pubkey = G1Element()
    cb_info = ClawbackInfo(TIMELOCK, pubkey)

    maker_p2_ph = cb_info.outer_puzzle().get_tree_hash()
    taker_p2_ph = ACS_PH

    primaries = [{"puzzle_hash": taker_p2_ph, "amount": amount}]

    cb_puz = cb_info.outer_puzzle()
    cb_sol = solve_cb_outer_puzzle(cb_info, primaries)

    merkle_puz = construct_p2_merkle_puzzle(cb_info, ACS_PH)

    # Set up a Clawback NFT (non-did)
    metadata = [
        ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
        ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
    ]
    metadata_updater_puzhash = NFT_METADATA_UPDATER.get_tree_hash()
    singleton_id = Program.to("singleton_id").get_tree_hash()
    lineage_proof = Program.to([singleton_id, maker_p2_ph, 1])
    nft_puz = create_full_puzzle(singleton_id, metadata, metadata_updater_puzhash, cb_puz)

    nft_layer_solution = Program.to([cb_sol])
    singleton_solution = Program.to([lineage_proof, amount, nft_layer_solution])

    conds = nft_puz.run(singleton_solution)

    merkle_nft = create_full_puzzle(singleton_id, metadata, metadata_updater_puzhash, merkle_puz)
    cc_cond = [c[1] for c in conds.as_python() if c[0] == b"3"][0]
    assert cc_cond == merkle_nft.get_tree_hash()
