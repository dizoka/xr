from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message


async def replace_with_text(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """Редагує текстове повідомлення, а якщо це неможливо — замінює його новим."""
    try:
        if message.photo or message.document or message.video:
            await message.delete()
            return await message.answer(text, reply_markup=reply_markup)
        return await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        return await message.answer(text, reply_markup=reply_markup)


async def replace_with_photo_or_text(
    bot: Bot,
    message: Message,
    *,
    text: str,
    photo_file_id: str | None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    if photo_file_id and len(text) <= 1000:
        return await bot.send_photo(
            chat_id=message.chat.id,
            photo=photo_file_id,
            caption=text,
            reply_markup=reply_markup,
        )
    if photo_file_id:
        await bot.send_photo(chat_id=message.chat.id, photo=photo_file_id)
    return await bot.send_message(
        chat_id=message.chat.id,
        text=text,
        reply_markup=reply_markup,
    )
