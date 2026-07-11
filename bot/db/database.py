from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import libsql

from bot.core.constants import DEFAULT_CATEGORIES, DEFAULT_SETTINGS


Row = Mapping[str, Any]


class Database:
    """Керує віддаленою SQLite-сумісною базою Turso."""

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
        def _connect() -> Any:
            return libsql.connect(
                database=self._database_url,
                auth_token=self._auth_token,
                _check_same_thread=False,
            )

        self._connection = await asyncio.to_thread(_connect)
        await self.execute("PRAGMA foreign_keys = ON")

    async def close(self) -> None:
        if self._connection is not None:
            connection = self._connection
            self._connection = None
            await asyncio.to_thread(connection.close)

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
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
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
                status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new', 'done')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_products_category
                ON products(category_id, in_stock, position, id);
            CREATE INDEX IF NOT EXISTS idx_inquiries_status
                ON inquiries(status, created_at);
        """

        async with self._lock:
            def _initialize() -> None:
                self.connection.executescript(schema)
                self.connection.commit()

            await asyncio.to_thread(_initialize)

        await self._seed_defaults()
        await self._migrate_ukrainian_defaults()

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
                    for position, (name, emoji) in enumerate(DEFAULT_CATEGORIES, start=1):
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
                "Добро пожаловать в каталог CrystalStore.\n\nВыберите нужный раздел ниже.":
                    DEFAULT_SETTINGS["welcome_text"],
            },
            "address_schedule": {
                "📍 Ковель\n🕒 Пн–Нд: 12:00–19:00\n\nТочный адрес уточняйте у продавца.":
                    DEFAULT_SETTINGS["address_schedule"],
            },
            "age_warning": {
                "🔞 Каталог предназначен только для совершеннолетних пользователей.\n\n"
                "Нажимая кнопку ниже, вы подтверждаете, что вам исполнилось 18 лет.":
                    DEFAULT_SETTINGS["age_warning"],
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

    async def execute(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> int:
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
        async with self._lock:
            def _fetchone() -> Row | None:
                cursor = self.connection.execute(query, tuple(parameters))
                row = cursor.fetchone()
                return self._row_to_dict(cursor, row)

            return await asyncio.to_thread(_fetchone)

    async def fetchall(
        self,
        query: str,
        parameters: Sequence[Any] = (),
    ) -> list[Row]:
        async with self._lock:
            def _fetchall() -> list[Row]:
                cursor = self.connection.execute(query, tuple(parameters))
                rows = cursor.fetchall()
                return [
                    self._row_to_dict(cursor, row) or {}
                    for row in rows
                ]

            return await asyncio.to_thread(_fetchall)
