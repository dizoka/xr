from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, TelegramObject


async def answer_callback_safely(
    callback: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> None:
    """Відповідає на callback без падіння через прострочений або вже закритий запит."""
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except TelegramBadRequest:
        # Callback Telegram живе недовго. На безкоштовному Render після сну
        # запит іноді встигає прострочитися, але саме меню все одно можна відкрити.
        pass


def parse_callback_ints(
    data: str | None, prefix: str, amount: int
) -> tuple[int, ...] | None:
    """Безпечно розбирає callback виду ``prefix:1:2``."""
    if not data or not data.startswith(prefix):
        return None
    tail = data[len(prefix) :]
    parts = tail.split(":") if tail else []
    if len(parts) != amount:
        return None
    try:
        return tuple(int(part) for part in parts)
    except (TypeError, ValueError):
        return None


class CallbackErrorMiddleware(BaseMiddleware):
    """Не дозволяє зламаній кнопці мовчки зависнути без відповіді."""

    def __init__(
        self,
        *,
        fallback_text: str = "Не вдалося відкрити цей розділ. Спробуйте ще раз.",
    ) -> None:
        self._fallback_text = fallback_text

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception:
            if isinstance(event, CallbackQuery):
                logging.exception(
                    "Помилка кнопки callback_data=%r user_id=%s",
                    event.data,
                    event.from_user.id,
                )
                await answer_callback_safely(
                    event,
                    self._fallback_text,
                    show_alert=True,
                )
                if event.message:
                    try:
                        await event.message.answer(
                            "⚠️ Не вдалося відкрити розділ. Надішліть /start і повторіть спробу."
                        )
                    except Exception:
                        logging.exception("Не вдалося надіслати резервне повідомлення")
                return None
            raise
