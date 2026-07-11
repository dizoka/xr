from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models import Category, Product
from bot.utils.text import product_title


def age_confirmation() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Мені вже є 18 років", callback_data="age:yes")
    builder.button(text="🚪 Вийти", callback_data="age:no")
    builder.adjust(1)
    return builder.as_markup()


def main_menu(contact_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🛍 Каталог", callback_data="u:catalog")
    builder.button(text="🔎 Пошук", callback_data="u:search")
    builder.button(text="📍 Адреса та графік", callback_data="u:info")
    if contact_url.startswith(("https://", "http://", "tg://")):
        builder.button(text="💬 Зв’язатися з продавцем", url=contact_url)
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def categories_menu(categories: list[Category]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.button(
            text=f"{category.emoji} {category.name}",
            callback_data=f"u:c:{category.id}:0",
        )
    builder.button(text="🏠 Головне меню", callback_data="u:home")
    builder.adjust(2, 1)
    return builder.as_markup()


def products_menu(
    products: list[Product],
    *,
    category_id: int,
    page: int,
    total_pages: int,
    currency: str,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in products:
        builder.button(
            text=f"{product_title(product)} — {product.price} {currency}",
            callback_data=f"u:p:{product.id}:{page}",
        )
    builder.adjust(1)

    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="◀️",
                callback_data=f"u:c:{category_id}:{page - 1}",
            )
        )
    if total_pages > 1:
        navigation.append(
            InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop")
        )
    if page + 1 < total_pages:
        navigation.append(
            InlineKeyboardButton(
                text="▶️",
                callback_data=f"u:c:{category_id}:{page + 1}",
            )
        )
    if navigation:
        builder.row(*navigation)

    builder.row(
        InlineKeyboardButton(text="◀️ Категорії", callback_data="u:catalog"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="u:home"),
    )
    return builder.as_markup()


def product_menu(product: Product, return_page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if product.in_stock:
        builder.button(
            text="📩 Дізнатися про наявність",
            callback_data=f"u:q:{product.id}",
        )
    builder.button(
        text="◀️ Назад до товарів",
        callback_data=f"u:c:{product.category_id}:{return_page}",
    )
    builder.button(text="🏠 Головне меню", callback_data="u:home")
    builder.adjust(1)
    return builder.as_markup()


def search_results(products: list[Product], currency: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in products:
        builder.button(
            text=f"{product_title(product)} — {product.price} {currency}",
            callback_data=f"u:p:{product.id}:0",
        )
    builder.button(text="🔎 Новий пошук", callback_data="u:search")
    builder.button(text="🏠 Головне меню", callback_data="u:home")
    builder.adjust(1)
    return builder.as_markup()


def back_home() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Головне меню", callback_data="u:home")
    return builder.as_markup()
