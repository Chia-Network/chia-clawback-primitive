from typing import List, Optional

from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.announcement import Announcement
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
    uncurry_clawback,
)


class CBManager:
    node_client: FullNodeRpcClient
    wallet_client: WalletRpcClient

    def __init__(self, node_client: FullNodeRpcClient, wallet_client: WalletRpcClient):
        self.node_client = node_client
        self.wallet_client = wallet_client
        # self.timelock = timelock

    async def get_private_key(self, index: uint32 = uint32(1)) -> PrivateKey:
        fp = await self.wallet_client.get_logged_in_fingerprint()
        sk_dict = await self.wallet_client.get_private_key(fp)
        master_sk = PrivateKey.from_bytes(hexstr_to_bytes(sk_dict["sk"]))
        private_key = master_sk_to_wallet_sk(master_sk, index)
        return private_key

    async def get_public_key(self, index: uint32 = uint32(1)) -> G1Element:
        private_key = await self.get_private_key(index)
        return private_key.get_g1()

    async def set_cb_info(self, timelock: uint32 = TWO_WEEKS) -> ClawbackInfo:
        self.timelock = timelock
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
        tx = await self.wallet_client.send_transaction(wallet_id, amount, address, fee)
        return tx

    async def get_cb_coin_by_id(self, coin_id: bytes32) -> Optional[CoinRecord]:
        return await self.node_client.get_coin_record_by_name(coin_id)

    async def get_cb_coins(self) -> List[CoinRecord]:
        return await self.node_client.get_coin_records_by_puzzle_hash(
            self.cb_info.puzzle_hash(), include_spent_coins=False
        )

    async def select_coins(self, amount: uint64) -> List[Coin]:
        cb_coin_recs = await self.get_cb_coins()
        cb_coin_recs.sort(key=lambda x: x.coin.amount, reverse=True)
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

    async def send_cb_coin(self, amount: uint64, target_puzzle_hash: bytes32, fee: uint64 = uint64(0)) -> SpendBundle:
        coins = await self.select_coins(uint64(amount + fee))
        # change = uint64(sum([coin.amount for coin in coins]) - amount)
        coin_spends = []
        amount_remaining: uint64 = amount
        fee_remaining: uint64 = fee

        for coin in coins:
            if coin.amount <= fee_remaining:
                # if the fee is greater than the coin amount, allocate it all to fee
                primaries: List = []
                change = uint64(0)
                cb_solution = solve_cb_outer_puzzle(self.cb_info, primaries, change, fee_remaining)
                fee_remaining = uint64(fee_remaining - coin.amount)
            else:
                # otherwise take the fee out and try to spend the rest of the amount remaining
                spend_amount = fee_remaining + amount_remaining
                if spend_amount <= coin.amount:
                    # the rest of the amount (and fee) can be spent by the current coin
                    change = uint64(coin.amount - spend_amount)
                    primaries = [{"puzzle_hash": target_puzzle_hash, "amount": amount_remaining}]
                    cb_solution = solve_cb_outer_puzzle(self.cb_info, primaries, change, fee_remaining)
                    fee_remaining = uint64(0)
                    amount_remaining = uint64(0)
                else:
                    # spend the full coin amount (with needed fee) and updated amount_remaining
                    amount_to_spend = uint64(coin.amount - fee_remaining)
                    primaries = [{"puzzle_hash": target_puzzle_hash, "amount": amount_to_spend}]
                    change = uint64(0)
                    cb_solution = solve_cb_outer_puzzle(self.cb_info, primaries, change, fee_remaining)
                    fee_remaining = uint64(0)
                    amount_remaining = uint64(amount_remaining - amount_to_spend)
            coin_spends.append(CoinSpend(coin, self.cb_info.outer_puzzle(), cb_solution))
        spend_bundle = await self.sign_coin_spends(coin_spends)
        return spend_bundle

    async def get_p2_merkle_coins(self, target_puzzle_hash: bytes32) -> List[Coin]:
        p2_merkle_ph = construct_p2_merkle_puzzle(self.cb_info, target_puzzle_hash).get_tree_hash()
        coin_recs = await self.node_client.get_coin_records_by_puzzle_hash(p2_merkle_ph, include_spent_coins=False)
        return [cr.coin for cr in coin_recs]

    async def clawback_p2_merkle(
        self, coins: List[Coin], target_puzzle_hash: bytes32, fee: uint64 = uint64(0)
    ) -> SpendBundle:
        p2_merkle_puz = construct_p2_merkle_puzzle(self.cb_info, target_puzzle_hash)
        coins.sort(key=lambda x: x.amount, reverse=True)
        coin_spends = []
        fee_remaining = fee
        # first = True
        for coin in coins:
            if fee_remaining >= coin.amount:
                claw_primary = {"puzzle_hash": self.cb_info.outer_puzzle().get_tree_hash(), "amount": coin.amount - fee}
                claw_primary = {}
                claw_sol = solve_p2_merkle_claw(self.cb_info, claw_primary, target_puzzle_hash, uint64(coin.amount))
                fee_remaining = uint64(fee_remaining - coin.amount)
            else:
                claw_primary = {
                    "puzzle_hash": self.cb_info.outer_puzzle().get_tree_hash(),
                    "amount": coin.amount - fee_remaining,
                }
                claw_sol = solve_p2_merkle_claw(self.cb_info, claw_primary, target_puzzle_hash, fee_remaining)
                fee_remaining = uint64(0)
            coin_spends.append(CoinSpend(coin, p2_merkle_puz, claw_sol))
        spend_bundle = await self.sign_coin_spends(coin_spends)
        return spend_bundle

    async def clawback_p2_merkle_coin_ids(
        self, coin_ids: List[bytes32], target_puzzle_hash: bytes32, fee: uint64 = uint64(0)
    ) -> SpendBundle:
        coin_recs = await self.node_client.get_coin_records_by_names(coin_ids)
        coins = [cr.coin for cr in coin_recs]
        return await self.clawback_p2_merkle(coins, target_puzzle_hash, fee)

    async def claim_p2_merkle(self, coin_id: bytes32, target_puzzle_hash: bytes32) -> SpendBundle:
        coin_rec = await self.node_client.get_coin_record_by_name(coin_id)
        assert isinstance(coin_rec, CoinRecord)
        coin = coin_rec.coin
        coin_spend = await self.node_client.get_puzzle_and_solution(
            coin.parent_coin_info, coin_rec.confirmed_block_index
        )
        assert isinstance(coin_spend, CoinSpend)
        puz = coin_spend.puzzle_reveal.to_program()
        timelock, sender_inner_puzzle = uncurry_clawback(puz)
        parent_coin_rec = await self.node_client.get_coin_record_by_name(coin.parent_coin_info)
        assert isinstance(parent_coin_rec, CoinRecord)
        cb_puzzle_hash = parent_coin_rec.coin.puzzle_hash
        p2_merkle_puz, claim_sol = solve_p2_merkle_claim(
            timelock, uint64(coin.amount), target_puzzle_hash, cb_puzzle_hash, sender_inner_puzzle
        )
        coin_spend = CoinSpend(coin, p2_merkle_puz, claim_sol)
        spend_bundle = SpendBundle([coin_spend], G2Element())
        return spend_bundle

    async def claim_p2_merkle_multiple(
        self, coin_ids: List[bytes32], target_puzzle_hash: bytes32, fee: uint64 = uint64(0), fee_wallet_id: int = 1
    ) -> SpendBundle:
        spend_bundles = []
        announcements = []
        for coin_id in coin_ids:
            claim_spend = await self.claim_p2_merkle(coin_id, target_puzzle_hash)
            spend_bundles.append(claim_spend)
            announcements.append(Announcement(coin_id, b""))
        fee_spend = await self.create_fee_spend(fee, announcements, fee_wallet_id)
        spend_bundles.append(fee_spend)
        return SpendBundle.aggregate(spend_bundles)

    async def create_fee_spend(self, fee: uint64, announcements: List[Announcement], fee_wallet_id: int) -> SpendBundle:
        spendable_coins = await self.wallet_client.get_spendable_coins(fee_wallet_id, min_coin_amount=fee)
        coin = spendable_coins[0][0].coin
        addition = {"puzzle_hash": coin.puzzle_hash, "amount": coin.amount - fee}
        fee_tx = await self.wallet_client.create_signed_transaction(
            [addition], coins=[coin], coin_announcements=announcements, fee=fee
        )
        assert isinstance(fee_tx.spend_bundle, SpendBundle)
        return fee_tx.spend_bundle