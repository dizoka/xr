from __future__ import annotations

from urllib.parse import urlparse

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models import Category, Product
from bot.utils.text import product_title


def _safe_contact_url(value: str | None) -> str | None:
    """Повертає лише придатне для Telegram посилання без пробілів і переносів."""
    if not value:
        return None
    url = value.strip()
    if any(char.isspace() for char in url):
        return None
    if url.startswith("tg://"):
        return url if len(url) > len("tg://") else None
    if not url.startswith(("https://", "http://")):
        return None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return url


def age_confirmation() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Мені вже є 18 років", callback_data="age:yes")
    builder.button(text="🚪 Вийти", callback_data="age:no")
    builder.adjust(1)
    return builder.as_markup()


def main_menu(contact_url: str = "") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🛍 Каталог", callback_data="u:catalog")
    builder.button(text="🔎 Пошук", callback_data="u:search")
    builder.button(text="📍 Адреса та графік", callback_data="u:info")

    safe_url = _safe_contact_url(contact_url)
    if safe_url:
        builder.button(text="💬 Зв’язатися з продавцем", url=safe_url)

    builder.adjust(2, 1, 1)
    return builder.as_markup()


def categories_menu(
    categories: list[Category],
    promotions_url: str = "",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    safe_promotions_url = _safe_contact_url(promotions_url)
    for category in categories:
        if category.name.strip().casefold() == "акції" and safe_promotions_url:
            builder.button(
                text=f"{category.emoji} {category.name}",
                url=safe_promotions_url,
            )
        else:
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


def fallback_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🛍 Каталог", callback_data="u:catalog")
    builder.button(text="🏠 Головне меню", callback_data="u:home")
    builder.adjust(1)
    return builder.as_markup()
