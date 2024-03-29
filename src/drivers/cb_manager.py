from typing import Dict, List, Optional, Tuple

from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey
from chia.consensus.block_record import BlockRecord
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import encode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_wallet_sk_unhardened
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    MOD,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    solution_for_conditions,
)
from clvm.casts import int_from_bytes, int_to_bytes

from src.drivers.cb_info import CBInfo
from src.drivers.cb_puzzles import P2_1_OF_N, create_clawback_puzzle, create_clawback_solution
from src.drivers.cb_store import CBStore

# Common Timelock Periods
ONE_HOUR = 60 * 60
ONE_DAY = ONE_HOUR * 24
ONE_WEEK = ONE_DAY * 7
TWO_WEEKS = ONE_WEEK * 2


class CBManager:
    node_client: FullNodeRpcClient
    wallet_client: WalletRpcClient
    cb_store: CBStore

    @classmethod
    async def create(cls, node_client: FullNodeRpcClient, wallet_client: WalletRpcClient, cb_store: CBStore):
        self = CBManager()
        self.node_client = node_client
        self.wallet_client = wallet_client
        self.cb_store = cb_store
        return self

    async def get_derivation_index(self) -> uint32:
        index = await self.wallet_client.get_current_derivation_index()
        return uint32(index)

    async def get_private_key(self) -> PrivateKey:
        fp = await self.wallet_client.get_logged_in_fingerprint()
        sk_dict = await self.wallet_client.get_private_key(fp)
        private_key = PrivateKey.from_bytes(hexstr_to_bytes(sk_dict["sk"]))
        return private_key

    async def get_keys_for_puzzle_hash(
        self, puzzle_hash: bytes32, max_index: Optional[uint32] = None
    ) -> Tuple[PrivateKey, int, bool]:
        private_key = await self.get_private_key()
        if not max_index:
            max_index = await self.get_derivation_index()
        for i in range(max_index):
            sk = master_sk_to_wallet_sk(private_key, uint32(i))
            ph = puzzle_for_pk(sk.get_g1()).get_tree_hash()
            if puzzle_hash == ph:
                return sk, i, True
            sk_u = master_sk_to_wallet_sk_unhardened(private_key, uint32(i))
            ph_u = puzzle_for_pk(sk_u.get_g1()).get_tree_hash()
            if puzzle_hash == ph_u:
                return sk_u, i, False
        raise ValueError(f"Couldn't find a matching key for puzzle hash: {puzzle_hash}.")

    async def get_puzzle_for_puzzle_hash(self, puzzle_hash: bytes32) -> Program:
        private_key, _, _ = await self.get_keys_for_puzzle_hash(puzzle_hash)
        return puzzle_for_pk(private_key.get_g1())

    def get_cb_puzzle(self, timelock: uint64, recipient_ph: bytes32, sender_ph: bytes32) -> Program:
        cb_puzzle = create_clawback_puzzle(timelock, sender_ph, recipient_ph)
        return cb_puzzle

    def get_cb_puzzle_hash(self, timelock: uint64, recipient_ph: bytes32, sender_ph: bytes32) -> bytes32:
        cb_puzzle = self.get_cb_puzzle(timelock, recipient_ph, sender_ph)
        return cb_puzzle.get_tree_hash()

    def get_cb_address(self, timelock: uint64, recipient_ph: bytes32, sender_ph: bytes32, prefix: str = "xch") -> str:
        puzzle_hash = self.get_cb_puzzle_hash(timelock, recipient_ph, sender_ph)
        return encode_puzzle_hash(puzzle_hash, prefix)

    async def create_cb_coin(
        self,
        amount: uint64,
        recipient_ph: bytes32,
        sender_ph: bytes32,
        timelock: uint64,
        fee: uint64 = uint64(0),
        wallet_id: int = 1,
    ) -> SpendBundle:
        total_amount = amount + fee
        coins = await self.wallet_client.select_coins(total_amount, wallet_id)
        assert len(coins) > 0
        spend_value = sum([coin.amount for coin in coins])
        change = spend_value - total_amount
        assert change >= 0

        spends: List[CoinSpend] = []
        message_list: List[bytes32] = [c.name() for c in coins]
        origin_coin = coins.copy().pop()
        origin_id = origin_coin.name()

        cb_puzzle_hash = self.get_cb_puzzle_hash(timelock, recipient_ph, sender_ph)
        cb_coin = Coin(origin_id, cb_puzzle_hash, amount)
        message_list.append(cb_coin.name())
        message = std_hash(b"".join(message_list))
        announcement_hash = Announcement(origin_coin.name(), message).name()

        secret_key, index, hardened = await self.get_keys_for_puzzle_hash(origin_coin.puzzle_hash)
        pk = secret_key.get_g1()
        puzzle = puzzle_for_pk(pk)
        assert puzzle.get_tree_hash() == origin_coin.puzzle_hash
        remark = sender_ph + recipient_ph + int_to_bytes(timelock)
        conditions = [
            [ConditionOpcode.CREATE_COIN, cb_puzzle_hash, amount],
            [ConditionOpcode.RESERVE_FEE, fee],
            [ConditionOpcode.REMARK, remark],
            [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, message],
        ]
        if change > 0:
            conditions.append([ConditionOpcode.CREATE_COIN, origin_coin.puzzle_hash, change])

        solution = solution_for_conditions(conditions)
        coin_spend = CoinSpend(origin_coin, puzzle, solution)
        spends.append(coin_spend)

        # Create the solutions for the rest of the xch coins
        for coin in coins:
            if coin.name() == origin_id:
                continue
            secret_key, index, hardened = await self.get_keys_for_puzzle_hash(coin.puzzle_hash)
            pk = secret_key.get_g1()
            puzzle = puzzle_for_pk(pk)
            conditions = [[ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, announcement_hash]]
            solution = solution_for_conditions(conditions)
            coin_spend = CoinSpend(coin, puzzle, solution)
            spends.append(coin_spend)

        spend = await self.sign_coin_spends(spends)
        return spend

    async def add_new_coin(self, coin: Coin, recipient_ph: bytes32, sender_ph: bytes32, timelock: uint64) -> None:
        cb_record = CBInfo(
            coin,
            recipient_ph,
            sender_ph,
            timelock,
            uint32(0),
            uint32(0),
            False,
            uint64(0),
        )
        await self.cb_store.add_coin_record(cb_record)

    async def update_coin_record(self, coin_id: bytes32) -> None:
        cb_info = await self.get_cb_info_by_id(coin_id)
        if cb_info:
            assert isinstance(cb_info, CBInfo)
            await self.cb_store.add_coin_record(cb_info)

    async def update_records(self) -> None:
        records = await self.cb_store.get_all_unspent_coins()
        for record in records:
            await self.update_coin_record(record.coin.name())

    async def get_cb_coin_by_id(self, coin_id: bytes32) -> Optional[CoinRecord]:
        coin_record = await self.node_client.get_coin_record_by_name(coin_id)
        return coin_record

    async def get_cb_info_by_id(self, coin_id: bytes32) -> Optional[CBInfo]:
        coin_record = await self.get_cb_coin_by_id(coin_id)
        if not coin_record:
            return None
        else:
            coin = coin_record.coin
        sender_ph, recipient_ph, timelock = await self.get_cb_details(coin)
        parent_cr = await self.node_client.get_coin_record_by_name(coin.parent_coin_info)
        assert isinstance(parent_cr, CoinRecord)
        block = await self.node_client.get_block_record_by_height(parent_cr.spent_block_index)
        assert isinstance(block, BlockRecord)
        assert isinstance(block.timestamp, uint64)
        timestamp: uint64 = block.timestamp
        cr = await self.node_client.get_coin_record_by_name(coin.name())
        assert isinstance(cr, CoinRecord)
        cb_info = CBInfo(
            coin,
            recipient_ph,
            sender_ph,
            timelock,
            cr.confirmed_block_index,
            cr.spent_block_index,
            cr.spent,
            timestamp,
        )
        return cb_info

    async def get_cb_coins(self) -> List[CBInfo]:
        records = await self.cb_store.get_all_unspent_coins()
        return sorted(records, key=lambda record: record.confirmed_block_height)

    async def create_clawback_spend(
        self, cb_info: CBInfo, to_puzzle_hash: bytes32, fee: uint64 = uint64(0)
    ) -> SpendBundle:
        puzzle = self.get_cb_puzzle(cb_info.timelock, cb_info.recipient_ph, cb_info.sender_ph)
        inner_puzzle = await self.get_puzzle_for_puzzle_hash(cb_info.sender_ph)
        assert inner_puzzle.get_tree_hash() == cb_info.sender_ph
        conditions = [
            [ConditionOpcode.CREATE_COIN, to_puzzle_hash, cb_info.coin.amount],
        ]
        if fee > uint64(0):
            fee_spend = await self.create_fee_spend(fee, [])
            fee_coin = fee_spend.removals()[0]
            message_list = [fee_spend.removals()[0].name(), fee_spend.additions()[0].name()]
            message = std_hash(b"".join(message_list))
            announcement = Announcement(fee_coin.name(), message)
            conditions.append([ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, announcement.name()])
        inner_solution = solution_for_conditions(conditions)
        solution = create_clawback_solution(
            cb_info.timelock, cb_info.sender_ph, cb_info.recipient_ph, inner_puzzle, inner_solution
        )
        coin_spend = CoinSpend(cb_info.coin, puzzle, solution)
        spend = await self.sign_coin_spends([coin_spend])
        if fee > uint64(0):
            full_spend = SpendBundle.aggregate([spend, fee_spend])
        else:
            full_spend = spend
        return full_spend

    async def get_cb_details(self, coin: Coin) -> Tuple:
        parent_cr = await self.node_client.get_coin_record_by_name(coin.parent_coin_info)
        assert isinstance(parent_cr, CoinRecord)
        parent_spend = await self.node_client.get_puzzle_and_solution(
            coin.parent_coin_info, parent_cr.spent_block_index
        )
        assert isinstance(parent_spend, CoinSpend)
        puzzle = parent_spend.puzzle_reveal.to_program()
        solution = parent_spend.solution.to_program()
        conditions = conditions_dict_for_solution(puzzle, solution, DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM)
        assert isinstance(conditions, Dict)
        if ConditionOpcode.REMARK in conditions.keys():
            remark = conditions[ConditionOpcode.REMARK][0].vars[0]
        else:
            raise ValueError("Coin doess not contain a valid clawback puzzle")
        sender_ph = bytes32(remark[:32])
        recipient_ph = bytes32(remark[32:64])
        timelock = int_from_bytes(remark[64:])
        return sender_ph, recipient_ph, timelock

    async def create_claim_spend(self, coin: Coin, claim_to: bytes32, fee: uint64 = uint64(0)) -> SpendBundle:
        sender_ph, recipient_ph, timelock = await self.get_cb_details(coin)
        puzzle = self.get_cb_puzzle(timelock, recipient_ph, sender_ph)
        inner_puzzle = await self.get_puzzle_for_puzzle_hash(recipient_ph)
        conditions = [[ConditionOpcode.CREATE_COIN, claim_to, coin.amount]]
        if fee > uint64(0):
            fee_spend = await self.create_fee_spend(fee, [])
            fee_coin = fee_spend.removals()[0]
            message_list = [fee_spend.removals()[0].name(), fee_spend.additions()[0].name()]
            message = std_hash(b"".join(message_list))
            announcement = Announcement(fee_coin.name(), message)
            conditions.append([ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, announcement.name()])
        inner_solution = solution_for_conditions(conditions)
        solution = create_clawback_solution(timelock, sender_ph, recipient_ph, inner_puzzle, inner_solution)
        coin_spend = CoinSpend(coin, puzzle, solution)
        spend = await self.sign_coin_spends([coin_spend])
        if fee > uint64(0):
            full_spend = SpendBundle.aggregate([spend, fee_spend])
        else:
            full_spend = spend
        return full_spend

    async def sign_coin_spends(self, coin_spends: List[CoinSpend]) -> SpendBundle:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        if config.get("selected_network") == "testnet10":
            hex_data = config["network_overrides"]["constants"]["testnet10"]["AGG_SIG_ME_ADDITIONAL_DATA"]
            additional_data = bytes.fromhex(hex_data)
        else:
            additional_data = DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA

        signatures: List[G2Element] = []
        pk_list: List[G1Element] = []
        msg_list: List[bytes] = []
        for coin_spend in coin_spends:
            # Get AGG_SIG conditions
            uncurried = coin_spend.puzzle_reveal.uncurry()
            if uncurried[0] == MOD:
                private_key, index, hardened = await self.get_keys_for_puzzle_hash(coin_spend.coin.puzzle_hash)
            elif uncurried[0] == P2_1_OF_N:
                inner_puz = coin_spend.solution.to_program().at("rrff")
                private_key, index, hardened = await self.get_keys_for_puzzle_hash(inner_puz.get_tree_hash())
            synthetic_secret_key = calculate_synthetic_secret_key(private_key, DEFAULT_HIDDEN_PUZZLE_HASH)

            conditions_dict = conditions_dict_for_solution(
                coin_spend.puzzle_reveal, coin_spend.solution, DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM
            )

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

    async def create_fee_spend(
        self, fee: uint64, announcements: List[Announcement], fee_wallet_id: int = 1
    ) -> SpendBundle:
        spendable_coins = await self.wallet_client.get_spendable_coins(fee_wallet_id, min_coin_amount=fee)
        coin = spendable_coins[0][0].coin
        addition = {"puzzle_hash": coin.puzzle_hash, "amount": coin.amount - fee}
        fee_tx = await self.wallet_client.create_signed_transaction(
            [addition], coins=[coin], coin_announcements=announcements, fee=fee
        )
        assert isinstance(fee_tx.spend_bundle, SpendBundle)
        return fee_tx.spend_bundle
