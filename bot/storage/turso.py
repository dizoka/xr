from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

from bot.db.database import Database


class TursoStorage(BaseStorage):
    """FSM-сховище aiogram у вже підключеній Turso-базі.

    Таблиця створюється автоматично під час ``Database.initialize()``, тому
    користувачеві не потрібно вручну змінювати Turso або додавати Redis.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _parts(key: StorageKey) -> tuple[int, int, int, int, str, str]:
        return (
            int(key.bot_id),
            int(key.chat_id),
            int(key.user_id),
            int(key.thread_id if key.thread_id is not None else -1),
            str(key.business_connection_id or ""),
            str(key.destiny or "default"),
        )

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        if isinstance(state, State):
            state_value: str | None = state.state
        elif state is None:
            state_value = None
        else:
            state_value = str(state)

        await self._database.execute(
            """
            INSERT INTO fsm_states(
                bot_id, chat_id, user_id, thread_id,
                business_connection_id, destiny, state, data, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', CURRENT_TIMESTAMP)
            ON CONFLICT(
                bot_id, chat_id, user_id, thread_id,
                business_connection_id, destiny
            ) DO UPDATE SET
                state = excluded.state,
                updated_at = CURRENT_TIMESTAMP
            """,
            (*self._parts(key), state_value),
        )

    async def get_state(self, key: StorageKey) -> str | None:
        row = await self._database.fetchone(
            """
            SELECT state FROM fsm_states
            WHERE bot_id = ? AND chat_id = ? AND user_id = ? AND thread_id = ?
              AND business_connection_id = ? AND destiny = ?
            """,
            self._parts(key),
        )
        if row is None or row.get("state") is None:
            return None
        return str(row["state"])

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        payload = json.dumps(dict(data), ensure_ascii=False, separators=(",", ":"))
        await self._database.execute(
            """
            INSERT INTO fsm_states(
                bot_id, chat_id, user_id, thread_id,
                business_connection_id, destiny, state, data, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(
                bot_id, chat_id, user_id, thread_id,
                business_connection_id, destiny
            ) DO UPDATE SET
                data = excluded.data,
                updated_at = CURRENT_TIMESTAMP
            """,
            (*self._parts(key), payload),
        )

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        row = await self._database.fetchone(
            """
            SELECT data FROM fsm_states
            WHERE bot_id = ? AND chat_id = ? AND user_id = ? AND thread_id = ?
              AND business_connection_id = ? AND destiny = ?
            """,
            self._parts(key),
        )
        if row is None:
            return {}
        try:
            value = json.loads(str(row.get("data") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    async def close(self) -> None:
        # З'єднання належить Database і закривається централізовано.
        return None
