from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InlineKeyboardMarkup


logger = logging.getLogger(__name__)


class NotificationService:
    """Надійно й паралельно надсилає службові повідомлення адміністраторам."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_many(
        self,
        chat_ids: set[int] | frozenset[int],
        text: str,
        *,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        await asyncio.gather(
            *(
                self._safe_send(chat_id, text, reply_markup=reply_markup)
                for chat_id in chat_ids
            ),
            return_exceptions=True,
        )

    async def _safe_send(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: InlineKeyboardMarkup | None,
    ) -> bool:
        for attempt in range(2):
            try:
                await self._bot.send_message(
                    chat_id,
                    text,
                    reply_markup=reply_markup,
                )
                return True
            except TelegramForbiddenError:
                logger.info("Чат адміністратора %s недоступний", chat_id)
                return False
            except TelegramBadRequest:
                logger.exception(
                    "Некоректне повідомлення для адміністратора %s", chat_id
                )
                return False
            except TelegramRetryAfter as exc:
                if attempt == 0:
                    await asyncio.sleep(float(exc.retry_after))
                    continue
                logger.warning("Rate limit при надсиланні адміністратору %s", chat_id)
                return False
            except (TelegramNetworkError, TelegramServerError):
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                logger.exception("Telegram тимчасово недоступний для чату %s", chat_id)
                return False
            except Exception:
                logger.exception(
                    "Невідома помилка надсилання адміністратору %s", chat_id
                )
                return False
        return False
