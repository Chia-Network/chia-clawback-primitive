from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional, Set

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32, uint64

from src.drivers.cb_manager import CBInfo


class CBStore:
    """
    This object handles CoinRecords for clawback coins.
    """

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, wrapper: DBWrapper2):
        self = cls()

        self.db_wrapper = wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS cb_record("
                    "coin_name text PRIMARY KEY,"
                    " confirmed_height bigint,"
                    " spent_height bigint,"
                    " spent int,"
                    " puzzle_hash text,"
                    " coin_parent text,"
                    " amount blob,"
                    " recipient_ph text,"
                    " sender_ph text,"
                    " timelock bigint,"
                    " timestamp bigint)"
                )
            )

            # Useful for reorg lookups
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_confirmed_height on cb_record(confirmed_height)")
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_spent_height on cb_record(spent_height)")
            await conn.execute("CREATE INDEX IF NOT EXISTS coin_spent on cb_record(spent)")

            await conn.execute("CREATE INDEX IF NOT EXISTS coin_puzzlehash on cb_record(puzzle_hash)")

            await conn.execute("CREATE INDEX IF NOT EXISTS coin_amount on cb_record(amount)")
            await conn.execute("CREATE INDEX IF NOT EXISTS recipients on cb_record(recipient_ph)")

        return self

    async def close(self) -> None:
        await self.db_wrapper.close()

    async def add_coin_record(self, record: CBInfo, name: Optional[bytes32] = None) -> None:
        if name is None:
            name = record.name()
        assert record.spent == (record.spent_block_height != 0)
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute_insert(
                "INSERT OR REPLACE INTO cb_record VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    name.hex(),
                    record.confirmed_block_height,
                    record.spent_block_height,
                    int(record.spent),
                    str(record.coin.puzzle_hash.hex()),
                    str(record.coin.parent_coin_info.hex()),
                    bytes(uint64(record.coin.amount)),
                    str(record.recipient_ph.hex()),
                    str(record.sender_ph.hex()),
                    int(record.timelock),
                    int(record.timestamp),
                ),
            )

    async def delete_coin_record(self, coin_name: bytes32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM cb_record WHERE coin_name=?", (coin_name.hex(),))).close()

    # Update coin_record to be spent in DB
    async def set_spent(self, coin_name: bytes32, height: uint32) -> None:

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute_insert(
                "UPDATE cb_record SET spent_height=?,spent=? WHERE coin_name=?",
                (
                    height,
                    1,
                    coin_name.hex(),
                ),
            )

    def cb_info_from_row(self, row: sqlite3.Row) -> CBInfo:
        coin = Coin(bytes32.fromhex(row[5]), bytes32.fromhex(row[4]), uint64.from_bytes(row[6]))
        return CBInfo(
            coin,
            bytes32.fromhex(row[7]),
            bytes32.fromhex(row[8]),
            uint64(row[9]),
            uint32(row[1]),
            uint32(row[2]),
            bool(row[3]),
            uint64(row[10]),
        )

    async def get_coin_record(self, coin_name: bytes32) -> Optional[CBInfo]:
        """Returns CBInfo with specified coin id."""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = list(await conn.execute_fetchall("SELECT * from cb_record WHERE coin_name=?", (coin_name.hex(),)))

        if len(rows) == 0:
            return None
        return self.cb_info_from_row(rows[0])

    async def get_coin_records(
        self,
        coin_names: List[bytes32],
        include_spent_coins: bool = True,
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2 ** 32) - 1),
    ) -> List[Optional[CBInfo]]:
        """Returns CBInfo with specified coin id."""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = list(
                await conn.execute_fetchall(
                    f"SELECT * from cb_record WHERE coin_name in ({','.join('?'*len(coin_names))}) "
                    f"AND confirmed_height>=? AND confirmed_height<? "
                    f"{'' if include_spent_coins else 'AND spent=0'}",
                    tuple([c.hex() for c in coin_names]) + (start_height, end_height),
                )
            )

        ret: Dict[bytes32, CBInfo] = {}
        for row in rows:
            record = self.cb_info_from_row(row)
            coin_name = bytes32.fromhex(row[0])
            ret[coin_name] = record

        return [ret.get(name) for name in coin_names]

    async def get_all_unspent_coins(self) -> Set[CBInfo]:
        """Returns set of cb coins that have not been spent yet."""
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall("SELECT * FROM cb_record WHERE spent_height=0")
        return set(self.cb_info_from_row(row) for row in rows)
