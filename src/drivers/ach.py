from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from blspy import G1Element
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, solution_for_conditions

from src.drivers.merkle_utils import build_merkle_tree
from src.load_clvm import load_clvm

CB_MOD = load_clvm("cb_outer.clsp", package_or_requirement="src.clsp")
CB_MOD_HASH = CB_MOD.get_tree_hash()
ACH_CLAWBACK_MOD = load_clvm("ach_clawback.clsp", package_or_requirement="src.clsp")
ACH_CLAWBACK_MOD_HASH = ACH_CLAWBACK_MOD.get_tree_hash()
ACH_COMPLETION_MOD = load_clvm("ach_completion.clsp", package_or_requirement="src.clsp")
ACH_COMPLETION_MOD_HASH = ACH_COMPLETION_MOD.get_tree_hash()
P2_MERKLE_MOD = load_clvm("p2_merkle_tree.clsp", package_or_requirement="src.clsp")
P2_MERKLE_MOD_HASH = P2_MERKLE_MOD.get_tree_hash()


@streamable
@dataclass(frozen=True)
class ClawbackInfo(Streamable):
    timelock: uint64
    amount: uint64
    pubkey: G1Element
    inner_puzzle: Program = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "inner_puzzle", puzzle_for_pk(self.pubkey))


def construct_cb_outer_puzzle(clawback_info: ClawbackInfo) -> Program:
    return CB_MOD.curry(
        CB_MOD_HASH,
        ACH_CLAWBACK_MOD_HASH,
        ACH_COMPLETION_MOD_HASH,
        P2_MERKLE_MOD_HASH,
        clawback_info.timelock,
        clawback_info.inner_puzzle.get_tree_hash(),
    )


def solve_cb_outer_puzzle(clawback_info: ClawbackInfo, primaries: List[Dict[str, Any]]) -> Program:
    conditions = [[51, primary["puzzle_hash"], primary["amount"]] for primary in primaries]
    inner_solution = solution_for_conditions(conditions)
    return Program.to([clawback_info.amount, clawback_info.inner_puzzle, inner_solution])


def construct_claim_puzzle(clawback_info: ClawbackInfo, target_ph: bytes32) -> Program:
    return ACH_COMPLETION_MOD.curry(clawback_info.timelock, target_ph)


def calculate_clawback_ph(clawback_info: ClawbackInfo) -> bytes32:
    return construct_cb_outer_puzzle(clawback_info).get_tree_hash()


def construct_clawback_puzzle(clawback_info: ClawbackInfo) -> Program:
    return ACH_CLAWBACK_MOD.curry(calculate_clawback_ph(clawback_info), clawback_info.inner_puzzle.get_tree_hash())


def calculate_merkle_tree(
    clawback_info: ClawbackInfo, target_ph: bytes32
) -> Tuple[bytes32, Dict[bytes32, Tuple[int, List[bytes32]]]]:
    return build_merkle_tree(
        [
            construct_clawback_puzzle(clawback_info).get_tree_hash(),
            construct_claim_puzzle(clawback_info, target_ph).get_tree_hash(),
        ]
    )


def construct_p2_merkle_puzzle(clawback_info: ClawbackInfo, target_ph: bytes32) -> Program:
    return P2_MERKLE_MOD.curry(calculate_merkle_tree(clawback_info, target_ph)[0])


def solve_claim_puzzle(amount: uint64) -> Program:
    return Program.to([amount])


def solve_claw_puzzle(clawback_info: ClawbackInfo, primary: Dict[str, Any]) -> Program:
    conditions = [[51, primary["puzzle_hash"], primary["amount"]]]
    inner_solution = solution_for_conditions(conditions)
    return Program.to([primary["amount"], clawback_info.inner_puzzle, inner_solution])


def solve_p2_merkle_claim(clawback_info: ClawbackInfo, amount: uint64, target_ph: bytes32) -> Program:
    claim_puz = construct_claim_puzzle(clawback_info, target_ph)
    claim_sol = solve_claim_puzzle(amount)
    merkle_tree = calculate_merkle_tree(clawback_info, target_ph)
    claim_proof = Program.to(merkle_tree[1][claim_puz.get_tree_hash()])
    return Program.to([claim_puz, claim_proof, claim_sol])


def solve_p2_merkle_claw(clawback_info: ClawbackInfo, primary: Dict[str, Any], target_ph: bytes32) -> Program:
    claw_puz = construct_clawback_puzzle(clawback_info)
    claw_sol = solve_claw_puzzle(clawback_info, primary)
    merkle_tree = calculate_merkle_tree(clawback_info, target_ph)
    claw_proof = Program.to(merkle_tree[1][claw_puz.get_tree_hash()])
    return Program.to([claw_puz, claw_proof, claw_sol])
