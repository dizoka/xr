from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, Message


logger = logging.getLogger(__name__)


async def _delete_safely(message: Message) -> None:
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def replace_with_text(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """Надійно показує текстове меню незалежно від типу поточного повідомлення."""

    if message.photo or message.document or message.video or message.animation:
        # Спочатку відправляємо нове повідомлення, щоб при помилці не залишити
        # користувача без меню, і лише потім прибираємо старе.
        new_message = await message.answer(text, reply_markup=reply_markup)
        await _delete_safely(message)
        return new_message

    try:
        return await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            try:
                await message.edit_reply_markup(reply_markup=reply_markup)
            except TelegramBadRequest:
                pass
            return message

        try:
            return await message.answer(text, reply_markup=reply_markup)
        except Exception:
            logger.exception("Не вдалося замінити повідомлення текстовим меню")
            raise


async def replace_with_photo_or_text(
    bot: Bot,
    message: Message,
    *,
    text: str,
    photo_file_id: str | None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """Показує картку товару та не видаляє старе меню до успішної відправки."""

    new_message: Message | None = None
    if photo_file_id and len(text) <= 1000:
        try:
            new_message = await bot.send_photo(
                chat_id=message.chat.id,
                photo=photo_file_id,
                caption=text,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest:
            logger.exception(
                "Не вдалося відправити фото товару, показуємо текстову картку"
            )

    if new_message is None and photo_file_id and len(text) > 1000:
        try:
            await bot.send_photo(chat_id=message.chat.id, photo=photo_file_id)
        except TelegramBadRequest:
            logger.exception("Не вдалося відправити окреме фото товару")

    if new_message is None:
        new_message = await bot.send_message(
            chat_id=message.chat.id,
            text=text,
            reply_markup=reply_markup,
        )

    await _delete_safely(message)
    return new_message
