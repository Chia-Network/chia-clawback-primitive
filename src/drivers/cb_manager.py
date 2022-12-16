from typing import List, Optional

from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import encode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.ints import uint32, uint64
from chia.wallet.derive_keys import master_sk_to_wallet_sk
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
)
from chia.wallet.transaction_record import TransactionRecord

from src.cb_utils import TWO_WEEKS
from src.drivers.cb_puzzles import (
    ClawbackInfo,
    construct_p2_merkle_puzzle,
    solve_cb_outer_puzzle,
    solve_p2_merkle_claim,
    solve_p2_merkle_claw,
)


class CBManager:
    node_client: FullNodeRpcClient
    wallet_client: WalletRpcClient

    def __init__(self, node_client: FullNodeRpcClient, wallet_client: WalletRpcClient, timelock: uint32 = TWO_WEEKS):
        self.node_client = node_client
        self.wallet_client = wallet_client
        self.timelock = timelock

    async def get_private_key(self, index: uint32 = uint32(1)) -> PrivateKey:
        fp = await self.wallet_client.get_logged_in_fingerprint()
        sk_dict = await self.wallet_client.get_private_key(fp)
        master_sk = PrivateKey.from_bytes(hexstr_to_bytes(sk_dict["sk"]))
        private_key = master_sk_to_wallet_sk(master_sk, index)
        return private_key

    async def get_public_key(self, index: uint32 = uint32(1)) -> G1Element:
        private_key = await self.get_private_key(index)
        return private_key.get_g1()

    async def set_cb_info(self) -> ClawbackInfo:
        pk = await self.get_public_key()
        self.cb_info = ClawbackInfo(self.timelock, pk)
        return self.cb_info

    async def get_cb_puzhash(self) -> bytes32:
        return self.cb_info.outer_puzzle().get_tree_hash()

    async def get_cb_address(self, prefix: str = "xch") -> str:
        puzhash = await self.get_cb_puzhash()
        return encode_puzzle_hash(puzhash, prefix)

    async def create_cb_coin(
        self, amount: uint64, address: str, wallet_id: int = 1, fee: uint64 = uint64(0)
    ) -> TransactionRecord:
        tx = await self.wallet_client.send_transaction(str(wallet_id), amount, address, fee)
        return tx

    async def get_cb_coin_by_id(self, coin_id: bytes32) -> Optional[CoinRecord]:
        return await self.node_client.get_coin_record_by_name(coin_id)

    async def get_cb_coins(self) -> List[CoinRecord]:
        return await self.node_client.get_coin_records_by_puzzle_hash(
            self.cb_info.puzzle_hash(), include_spent_coins=False
        )

    async def select_coins(self, amount: uint64) -> List[Coin]:
        cb_coin_recs = await self.get_cb_coins()
        cb_coin_recs.sort(key=lambda x: x.coin.amount)
        total = 0
        selected = []
        for coin_rec in cb_coin_recs:
            selected.append(coin_rec.coin)
            total += coin_rec.coin.amount
            if total >= amount:
                break
        return selected

    async def sign_coin_spends(self, coin_spends: List[CoinSpend]) -> SpendBundle:
        additional_data = DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA
        private_key = await self.get_private_key()
        synthetic_secret_key = calculate_synthetic_secret_key(private_key, DEFAULT_HIDDEN_PUZZLE_HASH)
        signatures: List[G2Element] = []
        pk_list: List[G1Element] = []
        msg_list: List[bytes] = []
        for coin_spend in coin_spends:
            # Get AGG_SIG conditions
            err, conditions_dict, cost = conditions_dict_for_solution(
                coin_spend.puzzle_reveal, coin_spend.solution, DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM
            )
            if err or conditions_dict is None:
                error_msg = f"Sign transaction failed, con:{conditions_dict}, error: {err}"
                raise ValueError(error_msg)

            # Create signature
            for pk_bytes, msg in pkm_pairs_for_conditions_dict(
                conditions_dict, coin_spend.coin.name(), additional_data
            ):
                pk = G1Element.from_bytes(pk_bytes)
                pk_list.append(pk)
                msg_list.append(msg)
                assert bytes(synthetic_secret_key.get_g1()) == bytes(pk)
                signature = AugSchemeMPL.sign(synthetic_secret_key, msg)
                assert AugSchemeMPL.verify(pk, msg, signature)
                signatures.append(signature)
        aggsig = AugSchemeMPL.aggregate(signatures)
        assert AugSchemeMPL.aggregate_verify(pk_list, msg_list, aggsig)
        return SpendBundle(coin_spends, aggsig)

    async def send_cb_coin(self, amount: uint64, target_puzzle_hash: bytes32) -> SpendBundle:
        # p2_merkle_ph = construct_p2_merkle_puzzle(self.cb_info, target_puzzle_hash).get_tree_hash()
        primaries = [{"puzzle_hash": target_puzzle_hash, "amount": amount}]
        cb_solution = solve_cb_outer_puzzle(self.cb_info, primaries)
        coins = await self.select_coins(amount)
        coin_spends = [CoinSpend(coin, self.cb_info.outer_puzzle(), cb_solution) for coin in coins]
        spend_bundle = await self.sign_coin_spends(coin_spends)
        # await self.node_client.push_tx(spend_bundle)
        return spend_bundle

    async def get_p2_merkle_coins(self, target_puzzle_hash: bytes32) -> List[Coin]:
        p2_merkle_ph = construct_p2_merkle_puzzle(self.cb_info, target_puzzle_hash).get_tree_hash()
        coin_recs = await self.node_client.get_coin_records_by_puzzle_hash(p2_merkle_ph, include_spent_coins=False)
        return [cr.coin for cr in coin_recs]

    async def clawback_p2_merkle(self, coin: Coin, target_puzzle_hash: bytes32) -> SpendBundle:
        p2_merkle_puz = construct_p2_merkle_puzzle(self.cb_info, target_puzzle_hash)
        claw_primary = {"puzzle_hash": self.cb_info.outer_puzzle().get_tree_hash(), "amount": coin.amount}
        claw_sol = solve_p2_merkle_claw(self.cb_info, claw_primary, target_puzzle_hash)
        coin_spends = [CoinSpend(coin, p2_merkle_puz, claw_sol)]
        spend_bundle = await self.sign_coin_spends(coin_spends)
        return spend_bundle

    async def claim_p2_merkle(self, coin: Coin, target_puzzle_hash: bytes32) -> SpendBundle:
        p2_merkle_puz = construct_p2_merkle_puzzle(self.cb_info, target_puzzle_hash)
        claim_sol = solve_p2_merkle_claim(self.cb_info, uint64(coin.amount), target_puzzle_hash)
        coin_spend = CoinSpend(coin, p2_merkle_puz, claim_sol)
        spend_bundle = SpendBundle([coin_spend], G2Element())
        return spend_bundle
