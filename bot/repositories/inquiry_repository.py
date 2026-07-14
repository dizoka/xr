from __future__ import annotations

from typing import Any

from bot.db.database import Database
from bot.models import Inquiry, Product


class InquiryRepository:
    """Зберігає заявки покупців зі snapshot товару на момент замовлення."""

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
            category_name=str(row.get("category_name", "")),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            variant=str(row.get("variant", "")),
            variant_label=str(row.get("variant_label", "")),
            comment=str(row.get("comment", "")),
        )

    async def create_snapshot(
        self,
        *,
        user_id: int,
        username: str | None,
        full_name: str,
        product: Product,
        variant_label: str = "",
        variant: str = "",
        comment: str = "",
        request_key: str | None = None,
    ) -> tuple[int, bool]:
        if request_key:
            existing = await self._database.fetchone(
                "SELECT id FROM inquiries WHERE request_key = ?",
                (request_key,),
            )
            if existing:
                return int(existing["id"]), False

        await self._database.execute(
            """
            INSERT OR IGNORE INTO inquiries(
                user_id, username, full_name, product_id,
                product_name_snapshot, product_price_snapshot,
                category_name_snapshot, variant_label_snapshot,
                variant, comment, request_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                full_name,
                product.id,
                product.name
                if not product.brand
                else f"{product.brand} {product.name}".strip(),
                product.price,
                product.category_name,
                variant_label,
                variant,
                comment,
                request_key,
            ),
        )

        if request_key:
            row = await self._database.fetchone(
                "SELECT id FROM inquiries WHERE request_key = ?",
                (request_key,),
            )
        else:
            row = await self._database.fetchone("SELECT last_insert_rowid() AS id")

        if row is None:
            raise RuntimeError("Не вдалося створити заявку")
        return int(row["id"]), True


    async def create_cart_snapshot(
        self,
        *,
        user_id: int,
        username: str | None,
        full_name: str,
        first_product_id: int,
        item_count: int,
        total_price: str,
        cart_details: str,
        request_key: str,
    ) -> tuple[int, bool]:
        """Створює одну заявку для всього кошика, а не окрему на кожен товар."""
        existing = await self._database.fetchone(
            "SELECT id FROM inquiries WHERE request_key = ?",
            (request_key,),
        )
        if existing:
            return int(existing["id"]), False

        await self._database.execute(
            """
            INSERT OR IGNORE INTO inquiries(
                user_id, username, full_name, product_id,
                product_name_snapshot, product_price_snapshot,
                category_name_snapshot, variant_label_snapshot,
                variant, comment, request_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', '', ?, ?)
            """,
            (
                user_id,
                username,
                full_name,
                first_product_id,
                f"Комплексне замовлення ({item_count} поз.)",
                total_price,
                "__cart__",
                cart_details,
                request_key,
            ),
        )
        row = await self._database.fetchone(
            "SELECT id FROM inquiries WHERE request_key = ?",
            (request_key,),
        )
        if row is None:
            raise RuntimeError("Не вдалося створити комплексну заявку")
        return int(row["id"]), True

    async def get(self, inquiry_id: int) -> Inquiry | None:
        row = await self._database.fetchone(
            """
            SELECT
                i.id, i.user_id, i.username, i.full_name, i.product_id,
                i.variant, i.comment, i.status, i.created_at,
                COALESCE(NULLIF(i.product_name_snapshot, ''), p.name, 'Видалений товар')
                    AS product_name,
                COALESCE(NULLIF(i.product_price_snapshot, ''), p.price, '—')
                    AS product_price,
                COALESCE(NULLIF(i.category_name_snapshot, ''), c.name, '')
                    AS category_name,
                COALESCE(i.variant_label_snapshot, '') AS variant_label
            FROM inquiries i
            LEFT JOIN products p ON p.id = i.product_id
            LEFT JOIN categories c ON c.id = p.category_id
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
                i.variant, i.comment, i.status, i.created_at,
                COALESCE(NULLIF(i.product_name_snapshot, ''), p.name, 'Видалений товар')
                    AS product_name,
                COALESCE(NULLIF(i.product_price_snapshot, ''), p.price, '—')
                    AS product_price,
                COALESCE(NULLIF(i.category_name_snapshot, ''), c.name, '')
                    AS category_name,
                COALESCE(i.variant_label_snapshot, '') AS variant_label
            FROM inquiries i
            LEFT JOIN products p ON p.id = i.product_id
            LEFT JOIN categories c ON c.id = p.category_id
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
