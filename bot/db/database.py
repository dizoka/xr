from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypeVar

import libsql

from bot.core.constants import DEFAULT_CATEGORIES, DEFAULT_SETTINGS


logger = logging.getLogger(__name__)
Row = Mapping[str, Any]
T = TypeVar("T")


class Database:
    """Керує віддаленою SQLite-сумісною базою Turso.

    Синхронний libsql виконується через ``asyncio.to_thread``, тому event loop
    Telegram-бота не блокується. Один lock захищає спільне з'єднання від
    одночасного доступу з різних worker threads.
    """

    def __init__(self, database_url: str, auth_token: str) -> None:
        self._database_url = database_url
        self._auth_token = auth_token
        self._connection: Any | None = None
        self._lock = asyncio.Lock()

    @property
    def connection(self) -> Any:
        if self._connection is None:
            raise RuntimeError("Базу даних не підключено")
        return self._connection

    async def connect(self) -> None:
        if self._connection is not None:
            return

        def _connect() -> Any:
            return libsql.connect(
                database=self._database_url,
                auth_token=self._auth_token,
                _check_same_thread=False,
            )

        self._connection = await asyncio.to_thread(_connect)
        await self.execute("PRAGMA foreign_keys = ON")

    async def close(self) -> None:
        if self._connection is None:
            return
        async with self._lock:
            connection = self._connection
            self._connection = None
            await asyncio.to_thread(connection.close)

    async def ping(self) -> bool:
        try:
            row = await asyncio.wait_for(self.fetchone("SELECT 1 AS ok"), timeout=5)
            return bool(row and int(row["ok"]) == 1)
        except Exception:
            logger.exception("Перевірка готовності Turso завершилася помилкою")
            return False

    @staticmethod
    def _row_to_dict(cursor: Any, row: Sequence[Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        description = cursor.description or ()
        columns = [str(item[0]) for item in description]
        return dict(zip(columns, row, strict=False))

    async def initialize(self) -> None:
        schema = """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                emoji TEXT NOT NULL DEFAULT '📦',
                position INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1))
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                brand TEXT NOT NULL DEFAULT '',
                price TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                photo_file_id TEXT,
                in_stock INTEGER NOT NULL DEFAULT 1 CHECK(in_stock IN (0, 1)),
                position INTEGER NOT NULL DEFAULT 0,
                quantity INTEGER NOT NULL DEFAULT 1,
                variant_type TEXT NOT NULL DEFAULT 'none',
                archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS age_confirmations (
                user_id INTEGER PRIMARY KEY,
                confirmed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS inquiries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT NOT NULL,
                product_id INTEGER NOT NULL,
                product_name_snapshot TEXT NOT NULL DEFAULT '',
                product_price_snapshot TEXT NOT NULL DEFAULT '',
                category_name_snapshot TEXT NOT NULL DEFAULT '',
                variant_label_snapshot TEXT NOT NULL DEFAULT '',
                variant TEXT NOT NULL DEFAULT '',
                comment TEXT NOT NULL DEFAULT '',
                request_key TEXT,
                status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new', 'done')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS staff_admins (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS fsm_states (
                bot_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL DEFAULT -1,
                business_connection_id TEXT NOT NULL DEFAULT '',
                destiny TEXT NOT NULL DEFAULT 'default',
                state TEXT,
                data TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(
                    bot_id, chat_id, user_id, thread_id,
                    business_connection_id, destiny
                )
            );
        """

        async with self._lock:

            def _initialize() -> None:
                self.connection.executescript(schema)

                category_columns = {
                    str(row[1])
                    for row in self.connection.execute(
                        "PRAGMA table_info(categories)"
                    ).fetchall()
                }
                if "archived" not in category_columns:
                    self.connection.execute(
                        "ALTER TABLE categories ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
                    )

                product_columns = {
                    str(row[1])
                    for row in self.connection.execute(
                        "PRAGMA table_info(products)"
                    ).fetchall()
                }
                if "quantity" not in product_columns:
                    self.connection.execute(
                        "ALTER TABLE products ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1"
                    )
                if "variant_type" not in product_columns:
                    self.connection.execute(
                        "ALTER TABLE products ADD COLUMN variant_type TEXT NOT NULL DEFAULT 'none'"
                    )
                if "archived" not in product_columns:
                    self.connection.execute(
                        "ALTER TABLE products ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
                    )
                self.connection.execute(
                    "UPDATE products SET quantity = 1 WHERE in_stock = 1 AND quantity = 0"
                )

                inquiry_columns = {
                    str(row[1])
                    for row in self.connection.execute(
                        "PRAGMA table_info(inquiries)"
                    ).fetchall()
                }
                migrations = {
                    "variant": "ALTER TABLE inquiries ADD COLUMN variant TEXT NOT NULL DEFAULT ''",
                    "comment": "ALTER TABLE inquiries ADD COLUMN comment TEXT NOT NULL DEFAULT ''",
                    "product_name_snapshot": (
                        "ALTER TABLE inquiries ADD COLUMN product_name_snapshot TEXT NOT NULL DEFAULT ''"
                    ),
                    "product_price_snapshot": (
                        "ALTER TABLE inquiries ADD COLUMN product_price_snapshot TEXT NOT NULL DEFAULT ''"
                    ),
                    "category_name_snapshot": (
                        "ALTER TABLE inquiries ADD COLUMN category_name_snapshot TEXT NOT NULL DEFAULT ''"
                    ),
                    "variant_label_snapshot": (
                        "ALTER TABLE inquiries ADD COLUMN variant_label_snapshot TEXT NOT NULL DEFAULT ''"
                    ),
                    "request_key": "ALTER TABLE inquiries ADD COLUMN request_key TEXT",
                }
                for column, statement in migrations.items():
                    if column not in inquiry_columns:
                        self.connection.execute(statement)

                # Заповнюємо snapshot для старих заявок без ручної міграції Turso.
                self.connection.execute(
                    """
                    UPDATE inquiries
                    SET product_name_snapshot = COALESCE(
                            NULLIF(product_name_snapshot, ''),
                            (SELECT p.name FROM products p WHERE p.id = inquiries.product_id),
                            'Видалений товар'
                        ),
                        product_price_snapshot = COALESCE(
                            NULLIF(product_price_snapshot, ''),
                            (SELECT p.price FROM products p WHERE p.id = inquiries.product_id),
                            '—'
                        ),
                        category_name_snapshot = COALESCE(
                            NULLIF(category_name_snapshot, ''),
                            (
                                SELECT c.name
                                FROM products p
                                JOIN categories c ON c.id = p.category_id
                                WHERE p.id = inquiries.product_id
                            ),
                            ''
                        )
                    """
                )

                # Старі товари отримують явний тип варіанта за поточною категорією.
                self.connection.execute(
                    """
                    UPDATE products
                    SET variant_type = 'color'
                    WHERE COALESCE(variant_type, 'none') IN ('', 'none')
                      AND category_id IN (
                          SELECT id FROM categories
                          WHERE lower(name) LIKE '%pod%'
                             OR name LIKE '%ПОД%'
                             OR name LIKE '%Под%'
                             OR name LIKE '%под%'
                             OR name LIKE '%Систем%'
                             OR name LIKE '%систем%'
                      )
                    """
                )
                self.connection.execute(
                    """
                    UPDATE products
                    SET variant_type = 'flavor'
                    WHERE COALESCE(variant_type, 'none') IN ('', 'none')
                      AND category_id IN (
                          SELECT id FROM categories
                          WHERE name LIKE '%Рід%'
                             OR name LIKE '%рід%'
                             OR name LIKE '%Жид%'
                             OR name LIKE '%жид%'
                             OR lower(name) LIKE '%liquid%'
                             OR lower(name) LIKE '%juice%'
                      )
                    """
                )

                self.connection.executescript(
                    """
                    CREATE INDEX IF NOT EXISTS idx_products_category
                        ON products(category_id, archived, in_stock, position, id);
                    CREATE INDEX IF NOT EXISTS idx_inquiries_status
                        ON inquiries(status, created_at);
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_inquiries_request_key
                        ON inquiries(request_key)
                        WHERE request_key IS NOT NULL;
                    CREATE INDEX IF NOT EXISTS idx_fsm_updated_at
                        ON fsm_states(updated_at);
                    """
                )
                # Незавершені сценарії старші двох діб більше не потрібні.
                self.connection.execute(
                    "DELETE FROM fsm_states WHERE updated_at < datetime('now', '-2 days')"
                )
                self.connection.commit()

            await asyncio.to_thread(_initialize)

        await self._seed_defaults()
        await self._migrate_ukrainian_defaults()
        await self._seed_cartridge_catalog()
        await self._seed_liquid_catalog()

    async def _seed_defaults(self) -> None:
        async with self._lock:

            def _seed() -> None:
                for key, value in DEFAULT_SETTINGS.items():
                    self.connection.execute(
                        "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                        (key, value),
                    )

                row = self.connection.execute(
                    "SELECT COUNT(*) FROM categories"
                ).fetchone()
                if row and int(row[0]) == 0:
                    for position, (name, emoji) in enumerate(
                        DEFAULT_CATEGORIES, start=1
                    ):
                        self.connection.execute(
                            """
                            INSERT INTO categories(name, emoji, position, active)
                            VALUES (?, ?, ?, 1)
                            """,
                            (name, emoji, position),
                        )
                self.connection.commit()

            await asyncio.to_thread(_seed)

    async def _migrate_ukrainian_defaults(self) -> None:
        setting_migrations = {
            "welcome_text": {
                "Добро пожаловать в каталог CrystalStore.\n\nВыберите нужный раздел ниже.": DEFAULT_SETTINGS[
                    "welcome_text"
                ],
            },
            "address_schedule": {
                "📍 Ковель\n🕒 Пн–Нд: 12:00–19:00\n\nТочный адрес уточняйте у продавца.": DEFAULT_SETTINGS[
                    "address_schedule"
                ],
            },
            "age_warning": {
                "🔞 Каталог предназначен только для совершеннолетних пользователей.\n\n"
                "Нажимая кнопку ниже, вы подтверждаете, что вам исполнилось 18 лет.": DEFAULT_SETTINGS[
                    "age_warning"
                ],
            },
        }
        category_migrations = {
            "Системы": "POD-системи",
            "Картриджи": "Картриджі",
            "Жидкости": "Рідини",
            "Акции": "Акції",
        }

        async with self._lock:

            def _migrate() -> None:
                for key, values in setting_migrations.items():
                    for old_value, new_value in values.items():
                        self.connection.execute(
                            "UPDATE settings SET value = ? WHERE key = ? AND value = ?",
                            (new_value, key, old_value),
                        )
                for old_name, new_name in category_migrations.items():
                    self.connection.execute(
                        "UPDATE categories SET name = ? WHERE name = ?",
                        (new_name, old_name),
                    )
                self.connection.commit()

            await asyncio.to_thread(_migrate)


    async def _seed_cartridge_catalog(self) -> None:
        """Одноразово додає картриджі зі списку магазину без ручної роботи в Turso.

        Додавання ідемпотентне: якщо товар з такою самою назвою вже існує
        у категорії картриджів, повторно він не створюється. Для всіх
        картриджів зі списку автоматично встановлюється ціна 150 грн.
        """
        cartridges = (
            ("OXVA", "Xlim 0.4 Ω", True),
            ("OXVA", "Xlim 0.6 Ω", True),
            ("OXVA", "Xlim 0.8 Ω", True),
            ("OXVA", "NeXLIM 0.6 Ω (2 мл)", False),
            ("OXVA", "NeXLIM 0.6 Ω (4 мл)", False),
            ("OXVA", "NeXLIM 0.8 Ω (2 мл)", True),
            ("Vaporesso", "XROS 0.4 Ω (3 мл)", True),
            ("Vaporesso", "XROS 0.6 Ω (2 мл)", True),
            ("Vaporesso", "XROS 0.6 Ω (3 мл)", False),
            ("Vaporesso", "XROS 0.8 Ω (2 мл)", True),
            ("Voopoo", "Vinci 0.8 Ω", True),
            ("Voopoo", "VMATE 0.7 Ω", False),
            ("Lost Vape", "0.6 Ω", True),
            ("Lost Vape", "0.8 Ω", True),
            ("Voopoo", "Argus 0.7 Ω", False),
            ("Voopoo", "Argus 0.4 Ω", True),
            ("Elf Bar", "ELFX 0.6 Ω", True),
        )

        async with self._lock:
            def _seed() -> None:
                category = self.connection.execute(
                    """
                    SELECT id FROM categories
                    WHERE archived = 0
                      AND (name = 'Картриджі' OR name = 'Картриджи' OR lower(name) LIKE '%cartridge%')
                    ORDER BY id ASC LIMIT 1
                    """
                ).fetchone()
                if category is None:
                    row = self.connection.execute(
                        "SELECT COALESCE(MAX(position), 0) + 1 FROM categories"
                    ).fetchone()
                    position = int(row[0]) if row else 1
                    cursor = self.connection.execute(
                        """
                        INSERT INTO categories(name, emoji, position, active, archived)
                        VALUES ('Картриджі', '🧩', ?, 1, 0)
                        """,
                        (position,),
                    )
                    category_id = int(cursor.lastrowid)
                else:
                    category_id = int(category[0])

                row = self.connection.execute(
                    "SELECT COALESCE(MAX(position), 0) FROM products WHERE category_id = ?",
                    (category_id,),
                ).fetchone()
                position = int(row[0]) if row else 0

                for brand, name, in_stock in cartridges:
                    exists = self.connection.execute(
                        """
                        SELECT 1 FROM products
                        WHERE category_id = ? AND archived = 0
                          AND lower(trim(brand)) = lower(trim(?))
                          AND lower(trim(name)) = lower(trim(?))
                        LIMIT 1
                        """,
                        (category_id, brand, name),
                    ).fetchone()
                    if exists:
                        self.connection.execute(
                            """
                            UPDATE products
                            SET price = '150',
                                description = CASE
                                    WHEN description IS NULL OR trim(description) = ''
                                         OR description LIKE '%точну ціну%'
                                    THEN 'Сумісність і наявність уточнюйте у продавця.'
                                    ELSE description
                                END
                            WHERE category_id = ? AND archived = 0
                              AND lower(trim(brand)) = lower(trim(?))
                              AND lower(trim(name)) = lower(trim(?))
                            """,
                            (category_id, brand, name),
                        )
                        continue
                    position += 1
                    self.connection.execute(
                        """
                        INSERT INTO products(
                            category_id, name, brand, price, description, photo_file_id,
                            in_stock, position, quantity, variant_type, archived
                        ) VALUES (?, ?, ?, '150', ?, NULL, ?, ?, 1, 'none', 0)
                        """,
                        (
                            category_id,
                            name,
                            brand,
                            "Сумісність і наявність уточнюйте у продавця.",
                            1 if in_stock else 0,
                            position,
                        ),
                    )
                self.connection.commit()

            await asyncio.to_thread(_seed)


    async def _seed_liquid_catalog(self) -> None:
        """Одноразово перебудовує рідини: одна категорія та віртуальні об'єми."""
        liquids: dict[int, tuple[tuple[str, str], ...]] = {
            10: (("Chaser", ""), ("Octobar", "NFT"), ("Flavorlab", "P1"), ("Flavorlab", "Puff"), ("Punch", "Neon")),
            15: (("Vape Shot", ""), ("Chaser", "Special Berry"), ("Flavorlab", "FL350 mini"), ("Lucky", ""), ("Octobar", "NFT"), ("Octobar", "X"), ("Octobar", "Fresh & Sour")),
            30: (
                ("Chaser", "For Pods"), ("Chaser", "Lux"), ("Chaser", "Black"),
                ("Chaser", "Special Berry"), ("Chaser", "Limitini Editini"),
                ("Chaser", "Halloween Limited"), ("Chaser", "Mix (Ultra)"),
                ("Chaser", "My Mint"), ("Chaser", "7 Years"),
                ("Chaser", "Christmas"), ("Chaser", "Beat"), ("Nova", ""),
                ("Lucky", ""), ("Octobar", "Twins"), ("Octobar", "Black Limit"),
                ("Flavorlab", "Lady"), ("Flavorlab", "Triple"),
                ("Flavorlab", "PE1000"), ("Flavorlab", "Aroma Max"),
                ("Flavorlab", "FL350"), ("M-Cake", ""),
            ),
        }
        async with self._lock:
            def _seed() -> None:
                migration_key = "liquid_catalog_single_category_v3"
                done = self.connection.execute(
                    "SELECT value FROM settings WHERE key = ?", (migration_key,)
                ).fetchone()
                if done and str(done[0]) == "1":
                    return

                rows = self.connection.execute(
                    """SELECT id, name FROM categories
                    WHERE archived = 0 AND (
                        lower(trim(name)) IN ('рідини', 'жидкости', 'liquids')
                        OR lower(trim(name)) LIKE 'рідини %мл'
                        OR lower(trim(name)) LIKE 'жидкости %мл'
                        OR lower(trim(name)) LIKE 'liquids %ml'
                    ) ORDER BY id ASC"""
                ).fetchall()

                parent_id = None
                for category_id, name in rows:
                    if str(name).strip().casefold() in {"рідини", "жидкости", "liquids"}:
                        parent_id = int(category_id)
                        break
                if parent_id is None:
                    pos = self.connection.execute(
                        "SELECT COALESCE(MAX(position), 0) + 1 FROM categories"
                    ).fetchone()[0]
                    cur = self.connection.execute(
                        "INSERT INTO categories(name, emoji, position, active, archived) VALUES ('Рідини', '💧', ?, 1, 0)",
                        (int(pos),),
                    )
                    parent_id = int(cur.lastrowid)

                self.connection.execute(
                    "UPDATE categories SET name='Рідини', emoji='💧', active=1, archived=0 WHERE id=?",
                    (parent_id,),
                )

                all_liquid_ids = [int(row[0]) for row in rows]
                if parent_id not in all_liquid_ids:
                    all_liquid_ids.append(parent_id)

                # Видаляємо всі старі товари рідин і службові категорії об'ємів.
                placeholders = ",".join("?" for _ in all_liquid_ids)
                self.connection.execute(
                    f"UPDATE products SET archived=1, in_stock=0 WHERE category_id IN ({placeholders})",
                    tuple(all_liquid_ids),
                )
                for category_id in all_liquid_ids:
                    if category_id != parent_id:
                        self.connection.execute(
                            "UPDATE categories SET active=0, archived=1 WHERE id=?",
                            (category_id,),
                        )

                position = 0
                for volume in (30, 15, 10):
                    for brand, name in liquids[volume]:
                        position += 1
                        self.connection.execute(
                            """INSERT INTO products(
                                category_id, name, brand, price, description, photo_file_id,
                                in_stock, position, quantity, variant_type, archived
                            ) VALUES (?, ?, ?, '0', ?, NULL, 1, ?, 1, 'none', 0)""",
                            (
                                parent_id,
                                name,
                                brand,
                                f"[volume:{volume}] Рідина {volume} мл. Наявність смаків уточнюйте у продавця.",
                                position,
                            ),
                        )

                self.connection.execute(
                    "INSERT OR REPLACE INTO settings(key, value) VALUES (?, '1')",
                    (migration_key,),
                )
                self.connection.commit()
            await asyncio.to_thread(_seed)

    async def execute(self, query: str, parameters: Sequence[Any] = ()) -> int:
        async with self._lock:

            def _execute() -> int:
                cursor = self.connection.execute(query, tuple(parameters))
                self.connection.commit()
                return int(cursor.lastrowid or 0)

            return await asyncio.to_thread(_execute)

    async def executemany(
        self,
        query: str,
        parameters: Iterable[Sequence[Any]],
    ) -> None:
        values = [tuple(row) for row in parameters]
        async with self._lock:

            def _executemany() -> None:
                self.connection.executemany(query, values)
                self.connection.commit()

            await asyncio.to_thread(_executemany)

    async def fetchone(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> Row | None:
        return await self._read_with_retry(self._fetchone_sync, query, parameters)

    async def fetchall(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> list[Row]:
        return await self._read_with_retry(self._fetchall_sync, query, parameters)

    async def _read_with_retry(
        self,
        operation: Any,
        query: str,
        parameters: Sequence[Any],
    ) -> Any:
        delay = 0.25
        for attempt in range(3):
            try:
                async with self._lock:
                    return await asyncio.to_thread(operation, query, tuple(parameters))
            except Exception:
                if attempt >= 2:
                    raise
                logger.warning(
                    "Тимчасова помилка читання Turso, повтор %s/3",
                    attempt + 2,
                    exc_info=True,
                )
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError("Недосяжний код")

    def _fetchone_sync(self, query: str, parameters: Sequence[Any]) -> Row | None:
        cursor = self.connection.execute(query, tuple(parameters))
        return self._row_to_dict(cursor, cursor.fetchone())

    def _fetchall_sync(self, query: str, parameters: Sequence[Any]) -> list[Row]:
        cursor = self.connection.execute(query, tuple(parameters))
        rows = cursor.fetchall()
        return [self._row_to_dict(cursor, row) or {} for row in rows]
