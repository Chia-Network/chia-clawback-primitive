from __future__ import annotations

from typing import List, Optional

from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.util.ints import uint32
from chia.wallet.util.wallet_types import WalletType

from src.cb_utils import TWO_WEEKS
from src.cb_wallet_info import CBWalletInfo


class CBWalletStore:
    """
    WalletUserStore keeps track of all user created wallets and necessary smart-contract data
    """

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2, timelock: Optional[uint32] = TWO_WEEKS):
        self = cls()

        self.db_wrapper = db_wrapper
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS cb_wallets("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    " name text,"
                    " wallet_type int,"
                    " data text,"
                    " timelock int)"
                )
            )

            await conn.execute("CREATE INDEX IF NOT EXISTS name on cb_wallets(name)")

            await conn.execute("CREATE INDEX IF NOT EXISTS type on cb_wallets(wallet_type)")

            await conn.execute("CREATE INDEX IF NOT EXISTS data on cb_wallets(data)")

        await self.init_wallet(timelock)
        return self

    async def init_wallet(self, timelock: Optional[uint32] = TWO_WEEKS):
        all_wallets = await self.get_all_wallet_info_entries()
        if len(all_wallets) == 0:
            await self.create_wallet("Chia Wallet", WalletType.STANDARD_WALLET, "", timelock)

    async def create_wallet(
        self,
        name: str,
        wallet_type: int,
        data: str,
        timelock: Optional[uint32] = TWO_WEEKS,
        id: Optional[int] = None,
    ) -> CBWalletInfo:

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT INTO cb_wallets VALUES(?, ?, ?, ?, ?)",
                (id, name, wallet_type, data, timelock),
            )
            await cursor.close()
            wallet = await self.get_last_wallet()
            if wallet is None:
                raise ValueError("Failed to get the just-created wallet")

        return wallet

    async def delete_wallet(self, id: int):
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM cb_wallets where id=?", (id,))).close()

    async def update_wallet(self, wallet_info: CBWalletInfo):
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT or REPLACE INTO cb_wallets VALUES(?, ?, ?, ?, ?)",
                (
                    wallet_info.id,
                    wallet_info.name,
                    wallet_info.type,
                    wallet_info.data,
                    wallet_info.timelock,
                ),
            )
            await cursor.close()

    async def get_last_wallet(self) -> Optional[CBWalletInfo]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(conn, "SELECT MAX(id) FROM cb_wallets")

        return None if row is None else await self.get_wallet_by_id(row[0])

    async def get_all_wallet_info_entries(self, wallet_type: Optional[WalletType] = None) -> List[CBWalletInfo]:
        """
        Return a set containing all wallets, optionally with a specific WalletType
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            if wallet_type is None:
                rows = await conn.execute_fetchall("SELECT * from cb_wallets")
            else:
                rows = await conn.execute_fetchall("SELECT * from cb_wallets WHERE wallet_type=?", (wallet_type.value,))
            return [CBWalletInfo(row[0], row[1], row[2], row[3], row[4]) for row in rows]

    async def get_wallet_by_id(self, id: int) -> Optional[CBWalletInfo]:
        """
        Return a wallet by id
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(conn, "SELECT * from cb_wallets WHERE id=?", (id,))

        return None if row is None else CBWalletInfo(row[0], row[1], row[2], row[3], row[4])
