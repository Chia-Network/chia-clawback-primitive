from blspy import G1Element
from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, solution_for_conditions

from src.drivers.cb_puzzles import create_clawback_puzzle, create_clawback_solution

ACS = Program.to(1)
ACS_PH = ACS.get_tree_hash()


def test_clawback_puzzles():
    timelock = 60
    amount = 1000
    pk = G1Element()
    sender_puz = puzzle_for_pk(pk)
    sender_ph = sender_puz.get_tree_hash()
    recipient_puz = ACS
    recipient_ph = ACS_PH

    clawback_puz = create_clawback_puzzle(timelock, sender_ph, recipient_ph)

    sender_sol = solution_for_conditions(
        [
            [51, sender_ph, amount],
        ]
    )

    cb_sender_sol = create_clawback_solution(timelock, sender_ph, recipient_ph, sender_puz, sender_sol)

    conds = clawback_puz.run(cb_sender_sol)
    assert conds

    recipient_sol = Program.to([[51, recipient_ph, amount]])
    cb_recipient_sol = create_clawback_solution(timelock, sender_ph, recipient_ph, recipient_puz, recipient_sol)
    conds = clawback_puz.run(cb_recipient_sol)
    assert conds
