from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import ErrorEvent

from bot.utils.callbacks import answer_callback_safely


logger = logging.getLogger(__name__)
router = Router(name="errors")


@router.error()
async def global_error_handler(event: ErrorEvent) -> bool:
    """Останній захисний рівень для необроблених помилок."""

    exc = event.exception
    if isinstance(exc, TelegramForbiddenError):
        logger.info("Telegram-чат недоступний: %s", exc)
        return True
    if isinstance(exc, TelegramRetryAfter):
        logger.warning("Telegram rate limit: повторити через %s с", exc.retry_after)
        return True
    if isinstance(exc, (TelegramNetworkError, TelegramServerError)):
        logger.warning("Тимчасова помилка Telegram: %s", exc)
        return True
    if isinstance(exc, TelegramBadRequest):
        logger.warning("Некоректний Telegram-запит: %s", exc)
        return True

    logger.error(
        "Необроблена помилка під час обробки update",
        exc_info=(type(exc), exc, exc.__traceback__),
    )

    # Користувач не залишається без пояснення, але помилка сповіщення
    # ніколи не перекриває первинну помилку.
    try:
        callback = event.update.callback_query
        if callback is not None:
            await answer_callback_safely(
                callback,
                "Сталася тимчасова помилка. Спробуйте ще раз.",
                show_alert=True,
            )
            if callback.message:
                await callback.message.answer(
                    "⚠️ Не вдалося виконати дію. Надішліть /start і повторіть спробу."
                )
        elif event.update.message is not None:
            await event.update.message.answer(
                "⚠️ Сталася тимчасова помилка. Спробуйте ще раз або надішліть /start."
            )
    except TelegramAPIError:
        logger.info("Не вдалося повідомити користувача про помилку")

    return True
