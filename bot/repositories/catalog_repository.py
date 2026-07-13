from __future__ import annotations

from time import monotonic
from typing import Any

from bot.db.database import Database
from bot.models import CatalogStats, Category, Product


class CatalogRepository:
    """Операції з налаштуваннями, категоріями, товарами та ролями."""

    _SETTINGS_TTL_SECONDS = 45.0

    def __init__(self, database: Database) -> None:
        self._database = database
        self._settings_cache: dict[str, tuple[str, float]] = {}

    @staticmethod
    def _category_from_row(row: Any) -> Category:
        return Category(
            id=int(row["id"]),
            name=str(row["name"]),
            emoji=str(row["emoji"]),
            position=int(row["position"]),
            active=bool(row["active"]),
        )

    @staticmethod
    def _product_from_row(row: Any) -> Product:
        return Product(
            id=int(row["id"]),
            category_id=int(row["category_id"]),
            category_name=str(row["category_name"]),
            category_emoji=str(row["category_emoji"]),
            name=str(row["name"]),
            brand=str(row["brand"]),
            price=str(row["price"]),
            description=str(row["description"]),
            photo_file_id=row["photo_file_id"],
            in_stock=bool(row["in_stock"]),
            position=int(row["position"]),
            quantity=int(row.get("quantity", 0)),
            variant_type=str(row.get("variant_type", "none")),
        )

    async def get_setting(self, key: str, default: str = "") -> str:
        now = monotonic()
        cached = self._settings_cache.get(key)
        if cached and cached[1] > now:
            return cached[0]

        row = await self._database.fetchone(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        )
        value = str(row["value"]) if row else default
        self._settings_cache[key] = (value, now + self._SETTINGS_TTL_SECONDS)
        return value

    async def set_setting(self, key: str, value: str) -> None:
        await self._database.execute(
            """
            INSERT INTO settings(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self._settings_cache[key] = (
            value,
            monotonic() + self._SETTINGS_TTL_SECONDS,
        )

    async def get_all_settings(self) -> dict[str, str]:
        rows = await self._database.fetchall("SELECT key, value FROM settings")
        values = {str(row["key"]): str(row["value"]) for row in rows}
        expires_at = monotonic() + self._SETTINGS_TTL_SECONDS
        for key, value in values.items():
            self._settings_cache[key] = (value, expires_at)
        return values

    async def is_age_confirmed(self, user_id: int) -> bool:
        row = await self._database.fetchone(
            "SELECT 1 AS ok FROM age_confirmations WHERE user_id = ?",
            (user_id,),
        )
        return row is not None

    async def confirm_age(self, user_id: int) -> None:
        await self._database.execute(
            """
            INSERT INTO age_confirmations(user_id, confirmed_at)
            VALUES (?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET confirmed_at = CURRENT_TIMESTAMP
            """,
            (user_id,),
        )

    async def list_categories(self, include_inactive: bool = False) -> list[Category]:
        active_filter = "" if include_inactive else "AND active = 1"
        rows = await self._database.fetchall(
            f"""
            SELECT id, name, emoji, position, active
            FROM categories
            WHERE archived = 0 {active_filter}
            ORDER BY position ASC, id ASC
            """
        )
        return [self._category_from_row(row) for row in rows]

    async def list_customer_categories(self) -> list[Category]:
        """Повертає тільки верхній рівень каталогу для покупця.

        Службові категорії об'ємів рідин залишаються доступними в адмін-панелі,
        але не дублюються в головному меню покупця.
        """
        rows = await self._database.fetchall(
            """
            SELECT id, name, emoji, position, active
            FROM categories
            WHERE archived = 0
              AND active = 1
              AND lower(trim(name)) NOT IN (
                  'рідини 10 мл', 'рідини 15 мл', 'рідини 30 мл',
                  'жидкости 10 мл', 'жидкости 15 мл', 'жидкости 30 мл'
              )
            ORDER BY position ASC, id ASC
            """
        )
        categories = [self._category_from_row(row) for row in rows]

        # Додатковий захист від старих дублікатів основної категорії «Рідини».
        result: list[Category] = []
        liquid_parent_added = False
        for category in categories:
            normalized = category.name.strip().casefold()
            if normalized in {"рідини", "жидкости", "liquids"}:
                if liquid_parent_added:
                    continue
                liquid_parent_added = True
            result.append(category)
        return result

    async def list_liquid_volume_categories(self) -> list[Category]:
        rows = await self._database.fetchall(
            """
            SELECT id, name, emoji, position, active
            FROM categories
            WHERE archived = 0
              AND active = 1
              AND lower(trim(name)) IN (
                  'рідини 10 мл', 'рідини 15 мл', 'рідини 30 мл',
                  'жидкости 10 мл', 'жидкости 15 мл', 'жидкости 30 мл'
              )
            ORDER BY
                CASE
                    WHEN name LIKE '%30%' THEN 1
                    WHEN name LIKE '%15%' THEN 2
                    WHEN name LIKE '%10%' THEN 3
                    ELSE 4
                END,
                id ASC
            """
        )
        return [self._category_from_row(row) for row in rows]

    async def get_category(self, category_id: int) -> Category | None:
        row = await self._database.fetchone(
            """
            SELECT id, name, emoji, position, active
            FROM categories
            WHERE id = ? AND archived = 0
            """,
            (category_id,),
        )
        return self._category_from_row(row) if row else None

    async def add_category(self, name: str, emoji: str) -> int:
        row = await self._database.fetchone(
            "SELECT COALESCE(MAX(position), 0) + 1 AS next_position FROM categories"
        )
        position = int(row["next_position"]) if row else 1
        return await self._database.execute(
            """
            INSERT INTO categories(name, emoji, position, active, archived)
            VALUES (?, ?, ?, 1, 0)
            """,
            (name, emoji, position),
        )

    async def update_category_name(self, category_id: int, name: str) -> None:
        await self._database.execute(
            "UPDATE categories SET name = ? WHERE id = ? AND archived = 0",
            (name, category_id),
        )

    async def update_category_emoji(self, category_id: int, emoji: str) -> None:
        await self._database.execute(
            "UPDATE categories SET emoji = ? WHERE id = ? AND archived = 0",
            (emoji, category_id),
        )

    async def toggle_category(self, category_id: int) -> None:
        await self._database.execute(
            """
            UPDATE categories
            SET active = CASE active WHEN 1 THEN 0 ELSE 1 END
            WHERE id = ? AND archived = 0
            """,
            (category_id,),
        )

    async def delete_category(self, category_id: int) -> None:
        # М'яке видалення зберігає старі замовлення та зв'язки в базі.
        await self._database.execute(
            "UPDATE categories SET archived = 1, active = 0 WHERE id = ?",
            (category_id,),
        )
        await self._database.execute(
            """
            UPDATE products
            SET archived = 1, in_stock = 0, quantity = 0
            WHERE category_id = ?
            """,
            (category_id,),
        )

    async def count_products(
        self, category_id: int, only_in_stock: bool = False
    ) -> int:
        stock_filter = "AND in_stock = 1" if only_in_stock else ""
        row = await self._database.fetchone(
            f"""
            SELECT COUNT(*) AS total
            FROM products
            WHERE category_id = ? AND archived = 0 {stock_filter}
            """,
            (category_id,),
        )
        return int(row["total"]) if row else 0

    async def list_products(
        self,
        category_id: int,
        *,
        limit: int,
        offset: int,
        only_in_stock: bool = False,
    ) -> list[Product]:
        stock_filter = "AND p.in_stock = 1" if only_in_stock else ""
        rows = await self._database.fetchall(
            f"""
            SELECT
                p.id, p.category_id, p.name, p.brand, p.price, p.description,
                p.photo_file_id, p.in_stock, p.position, p.quantity, p.variant_type,
                c.name AS category_name, c.emoji AS category_emoji
            FROM products p
            JOIN categories c ON c.id = p.category_id
            WHERE p.category_id = ?
              AND p.archived = 0
              AND c.archived = 0
              {stock_filter}
            ORDER BY p.position ASC, p.id ASC
            LIMIT ? OFFSET ?
            """,
            (category_id, limit, offset),
        )
        return [self._product_from_row(row) for row in rows]

    async def get_product(self, product_id: int) -> Product | None:
        row = await self._database.fetchone(
            """
            SELECT
                p.id, p.category_id, p.name, p.brand, p.price, p.description,
                p.photo_file_id, p.in_stock, p.position, p.quantity, p.variant_type,
                c.name AS category_name, c.emoji AS category_emoji
            FROM products p
            JOIN categories c ON c.id = p.category_id
            WHERE p.id = ? AND p.archived = 0 AND c.archived = 0
            """,
            (product_id,),
        )
        return self._product_from_row(row) if row else None

    async def search_products(self, query: str, limit: int = 20) -> list[Product]:
        pattern = f"%{query.strip()}%"
        rows = await self._database.fetchall(
            """
            SELECT
                p.id, p.category_id, p.name, p.brand, p.price, p.description,
                p.photo_file_id, p.in_stock, p.position, p.quantity, p.variant_type,
                c.name AS category_name, c.emoji AS category_emoji
            FROM products p
            JOIN categories c ON c.id = p.category_id
            WHERE c.active = 1
              AND c.archived = 0
              AND p.archived = 0
              AND p.in_stock = 1
              AND (p.name LIKE ? COLLATE NOCASE OR p.brand LIKE ? COLLATE NOCASE)
            ORDER BY p.position ASC, p.id ASC
            LIMIT ?
            """,
            (pattern, pattern, limit),
        )
        return [self._product_from_row(row) for row in rows]

    async def add_product(
        self,
        *,
        category_id: int,
        name: str,
        brand: str,
        price: str,
        description: str,
        photo_file_id: str | None,
        variant_type: str = "none",
    ) -> int:
        row = await self._database.fetchone(
            """
            SELECT COALESCE(MAX(position), 0) + 1 AS next_position
            FROM products WHERE category_id = ?
            """,
            (category_id,),
        )
        position = int(row["next_position"]) if row else 1
        return await self._database.execute(
            """
            INSERT INTO products(
                category_id, name, brand, price, description,
                photo_file_id, in_stock, position, quantity, variant_type, archived
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, 1, ?, 0)
            """,
            (
                category_id,
                name,
                brand,
                price,
                description,
                photo_file_id,
                position,
                variant_type,
            ),
        )

    async def update_product_field(
        self, product_id: int, field: str, value: Any
    ) -> None:
        allowed_fields = {
            "name",
            "brand",
            "price",
            "description",
            "photo_file_id",
            "category_id",
            "quantity",
            "variant_type",
        }
        if field not in allowed_fields:
            raise ValueError(f"Unsupported product field: {field}")
        await self._database.execute(
            f"UPDATE products SET {field} = ? WHERE id = ? AND archived = 0",
            (value, product_id),
        )

    async def toggle_product_stock(self, product_id: int) -> None:
        await self._database.execute(
            """
            UPDATE products
            SET in_stock = CASE in_stock WHEN 1 THEN 0 ELSE 1 END
            WHERE id = ? AND archived = 0
            """,
            (product_id,),
        )

    async def delete_product(self, product_id: int) -> None:
        # М'яке видалення не знищує заявки через ON DELETE CASCADE.
        await self._database.execute(
            """
            UPDATE products
            SET archived = 1, in_stock = 0, quantity = 0
            WHERE id = ?
            """,
            (product_id,),
        )

    async def set_product_quantity(self, product_id: int, quantity: int) -> None:
        quantity = max(0, int(quantity))
        await self._database.execute(
            """
            UPDATE products
            SET quantity = ?, in_stock = CASE WHEN ? > 0 THEN 1 ELSE 0 END
            WHERE id = ? AND archived = 0
            """,
            (quantity, quantity, product_id),
        )

    async def add_staff_admin(self, user_id: int) -> None:
        await self._database.execute(
            "INSERT OR IGNORE INTO staff_admins(user_id) VALUES (?)",
            (user_id,),
        )

    async def remove_staff_admin(self, user_id: int) -> None:
        await self._database.execute(
            "DELETE FROM staff_admins WHERE user_id = ?",
            (user_id,),
        )

    async def is_staff_admin(self, user_id: int) -> bool:
        row = await self._database.fetchone(
            "SELECT 1 AS ok FROM staff_admins WHERE user_id = ?",
            (user_id,),
        )
        return row is not None

    async def list_staff_admins(self) -> list[int]:
        rows = await self._database.fetchall(
            "SELECT user_id FROM staff_admins ORDER BY added_at ASC"
        )
        return [int(row["user_id"]) for row in rows]

    async def stats(self) -> CatalogStats:
        row = await self._database.fetchone(
            """
            SELECT
                (SELECT COUNT(*) FROM categories WHERE archived = 0) AS categories,
                (SELECT COUNT(*) FROM products WHERE archived = 0) AS products,
                (
                    SELECT COUNT(*) FROM products
                    WHERE archived = 0 AND in_stock = 1
                ) AS in_stock,
                (SELECT COUNT(*) FROM inquiries WHERE status = 'new') AS open_inquiries
            """
        )
        if row is None:
            return CatalogStats(0, 0, 0, 0)
        return CatalogStats(
            categories=int(row["categories"]),
            products=int(row["products"]),
            in_stock=int(row["in_stock"]),
            open_inquiries=int(row["open_inquiries"]),
        )
