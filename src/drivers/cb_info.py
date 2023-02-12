from dataclasses import dataclass

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import Coin
from chia.util.ints import uint32, uint64

@dataclass(frozen=True)
class CBInfo:
    coin: Coin
    recipient_ph: bytes32
    sender_ph: bytes32
    timelock: uint64
    confirmed_block_height: uint32
    spent_block_height: uint32
    spent: bool
    key_derivation_index: int
    hardened: bool
    timestamp: uint64

    def name(self) -> bytes32:
        return self.coin.name()
