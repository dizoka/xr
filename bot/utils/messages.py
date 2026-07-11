from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, Message


async def replace_with_text(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """Надійно показує текстове меню незалежно від типу поточного повідомлення."""
    if message.photo or message.document or message.video or message.animation:
        try:
            await message.delete()
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
        return await message.answer(text, reply_markup=reply_markup)

    try:
        return await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        # Якщо текст та клавіатура не змінилися, Telegram повертає помилку.
        # У такому випадку кнопка вже фактично спрацювала.
        if "message is not modified" in str(exc).lower():
            try:
                await message.edit_reply_markup(reply_markup=reply_markup)
            except TelegramBadRequest:
                pass
            return message
        try:
            return await message.answer(text, reply_markup=reply_markup)
        except Exception:
            logging.exception("Не вдалося замінити повідомлення текстовим меню")
            raise


async def replace_with_photo_or_text(
    bot: Bot,
    message: Message,
    *,
    text: str,
    photo_file_id: str | None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """Показує картку товару; при зламаному file_id автоматично показує текст."""
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError):
        pass

    if photo_file_id and len(text) <= 1000:
        try:
            return await bot.send_photo(
                chat_id=message.chat.id,
                photo=photo_file_id,
                caption=text,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest:
            logging.exception("Не вдалося відправити фото товару, показуємо текстову картку")

    if photo_file_id and len(text) > 1000:
        try:
            await bot.send_photo(chat_id=message.chat.id, photo=photo_file_id)
        except TelegramBadRequest:
            logging.exception("Не вдалося відправити окреме фото товару")

    return await bot.send_message(
        chat_id=message.chat.id,
        text=text,
        reply_markup=reply_markup,
    )
