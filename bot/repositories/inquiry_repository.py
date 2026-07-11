from __future__ import annotations

from typing import Any

from bot.db.database import Database
from bot.models import Inquiry


class InquiryRepository:
    """Зберігає та отримує запити покупців щодо товарів."""

    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _from_row(row: Any) -> Inquiry:
        return Inquiry(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            username=row["username"],
            full_name=str(row["full_name"]),
            product_id=int(row["product_id"]),
            product_name=str(row["product_name"]),
            product_price=str(row["product_price"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
        )

    async def create(
        self,
        *,
        user_id: int,
        username: str | None,
        full_name: str,
        product_id: int,
    ) -> tuple[int, bool]:
        existing = await self._database.fetchone(
            """
            SELECT id FROM inquiries
            WHERE user_id = ? AND product_id = ? AND status = 'new'
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, product_id),
        )
        if existing:
            return int(existing["id"]), False

        inquiry_id = await self._database.execute(
            """
            INSERT INTO inquiries(user_id, username, full_name, product_id)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, username, full_name, product_id),
        )
        return inquiry_id, True

    async def get(self, inquiry_id: int) -> Inquiry | None:
        row = await self._database.fetchone(
            """
            SELECT
                i.id, i.user_id, i.username, i.full_name, i.product_id,
                i.status, i.created_at,
                p.name AS product_name, p.price AS product_price
            FROM inquiries i
            JOIN products p ON p.id = i.product_id
            WHERE i.id = ?
            """,
            (inquiry_id,),
        )
        return self._from_row(row) if row else None

    async def list_open(self, limit: int = 20) -> list[Inquiry]:
        rows = await self._database.fetchall(
            """
            SELECT
                i.id, i.user_id, i.username, i.full_name, i.product_id,
                i.status, i.created_at,
                p.name AS product_name, p.price AS product_price
            FROM inquiries i
            JOIN products p ON p.id = i.product_id
            WHERE i.status = 'new'
            ORDER BY i.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._from_row(row) for row in rows]

    async def mark_done(self, inquiry_id: int) -> None:
        await self._database.execute(
            "UPDATE inquiries SET status = 'done' WHERE id = ?",
            (inquiry_id,),
        )
