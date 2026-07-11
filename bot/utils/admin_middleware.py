from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.repositories.catalog_repository import CatalogRepository


class AdminOnlyMiddleware(BaseMiddleware):
    """Надає власнику та виданим адміністраторам повний доступ до панелі."""

    # Працівники з виданою адмінкою мають повний доступ до інтерфейсу.
    # Команди керування іншими адміністраторами все одно доступні лише власнику.


    def __init__(self, owner_ids: frozenset[int], catalog: CatalogRepository) -> None:
        self._owner_ids = owner_ids
        self._catalog = catalog

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return None

        is_owner = user.id in self._owner_ids
        is_staff = False if is_owner else await self._catalog.is_staff_admin(user.id)
        data["is_owner_admin"] = is_owner
        data["is_staff_admin"] = is_staff

        if is_owner:
            return await handler(event, data)

        if is_staff:
            if isinstance(event, Message):
                # Доступ до /admin та всіх кроків FSM у повній адмін-панелі.
                if event.text and event.text.startswith("/admin"):
                    return await handler(event, data)
                if data.get("raw_state"):
                    return await handler(event, data)
            elif isinstance(event, CallbackQuery):
                # Повний доступ до всіх кнопок адмін-панелі.
                if (event.data or "").startswith("a:"):
                    return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer("Немає доступу до цієї дії", show_alert=True)
        elif isinstance(event, Message) and event.text and event.text.startswith("/admin"):
            await event.answer("У вас немає доступу до адмін-панелі.")
        return None
