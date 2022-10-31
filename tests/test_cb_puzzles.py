from blspy import G1Element
from chia.types.blockchain_format.program import Program
from clvm.casts import int_to_bytes

from src.drivers.ach import (
    ClawbackInfo,
    construct_cb_outer_puzzle,
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


def test_clawback_xch():
    amount = 10000
    TIMELOCK = 100
    pubkey = G1Element()
    cb_info = ClawbackInfo(TIMELOCK, amount, pubkey)
    amt_1 = 200
    amt_2 = 800
    primaries = [{"puzzle_hash": ACS_PH, "amount": amt_1}, {"puzzle_hash": ACS_PH, "amount": amt_2}]

    cb_puz = construct_cb_outer_puzzle(cb_info)
    cb_sol = solve_cb_outer_puzzle(cb_info, primaries)

    cb_conds = cb_puz.run(cb_sol).as_python()

    merkle_puz = construct_p2_merkle_puzzle(cb_info, ACS_PH)
    merkle_ph = merkle_puz.get_tree_hash()

    expected_conds = [
        [b"3", merkle_ph, int_to_bytes(amt_1)],
        [b"3", merkle_ph, int_to_bytes(amt_2)],
        [b"3", cb_puz.get_tree_hash(), int_to_bytes(amount - amt_1 - amt_2)],
    ]

    for cond in expected_conds:
        assert cond in cb_conds

    # Create claim and clawback solutions
    claw_primary = {"puzzle_hash": cb_puz.get_tree_hash(), "amount": amt_1}
    claw_sol = solve_p2_merkle_claw(cb_info, claw_primary, ACS_PH)
    claim_sol = solve_p2_merkle_claim(cb_info, amt_2, ACS_PH)

    # Run clawback
    claw_merkle_conds = merkle_puz.run(claw_sol)
    expected_cond = [b"3", cb_puz.get_tree_hash(), int_to_bytes(amt_1)]
    assert expected_cond in claw_merkle_conds.as_python()

    # Run claim
    claim_merkle_conds = merkle_puz.run(claim_sol)
    expected_cond = [b"3", ACS_PH, int_to_bytes(amt_2)]
    assert expected_cond in claim_merkle_conds.as_python()
