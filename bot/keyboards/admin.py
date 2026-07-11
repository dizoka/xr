from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models import Category, Inquiry, Product
from bot.utils.text import product_title


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📂 Категорії", callback_data="a:cats")
    builder.button(text="📦 Товари", callback_data="a:products")
    builder.button(text="📝 Запити", callback_data="a:reqs")
    builder.button(text="⚙️ Налаштування", callback_data="a:settings")
    builder.button(text="📊 Статистика", callback_data="a:stats")
    builder.button(text="👁 Відкрити каталог", callback_data="u:home")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def categories_list(categories: list[Category]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in categories:
        status = "✅" if category.active else "⛔"
        builder.button(
            text=f"{status} {category.emoji} {category.name}",
            callback_data=f"a:cat:{category.id}",
        )
    builder.button(text="➕ Додати категорію", callback_data="a:catadd")
    builder.button(text="◀️ Адмін-панель", callback_data="a:home")
    builder.adjust(1)
    return builder.as_markup()


def category_actions(category: Category) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Змінити назву", callback_data=f"a:catname:{category.id}")
    builder.button(text="😀 Змінити емодзі", callback_data=f"a:catemoji:{category.id}")
    builder.button(
        text="⛔ Приховати" if category.active else "✅ Показати",
        callback_data=f"a:cattoggle:{category.id}",
    )
    builder.button(text="🗑 Видалити", callback_data=f"a:catdel:{category.id}")
    builder.button(text="◀️ Категорії", callback_data="a:cats")
    builder.adjust(1)
    return builder.as_markup()


def confirm_category_delete(category_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Так, видалити", callback_data=f"a:catdelok:{category_id}")
    builder.button(text="Скасувати", callback_data=f"a:cat:{category_id}")
    builder.adjust(1)
    return builder.as_markup()


def product_categories(categories: list[Category]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.button(
            text=f"{category.emoji} {category.name}",
            callback_data=f"a:plist:{category.id}:0",
        )
    builder.button(text="◀️ Адмін-панель", callback_data="a:home")
    builder.adjust(2, 1)
    return builder.as_markup()


def admin_products_list(
    products: list[Product],
    *,
    category_id: int,
    page: int,
    total_pages: int,
    currency: str,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in products:
        status = "✅" if product.in_stock else "⛔"
        builder.button(
            text=f"{status} {product_title(product)} — {product.price} {currency}",
            callback_data=f"a:p:{product.id}:{page}",
        )
    builder.adjust(1)

    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="◀️",
                callback_data=f"a:plist:{category_id}:{page - 1}",
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
                callback_data=f"a:plist:{category_id}:{page + 1}",
            )
        )
    if navigation:
        builder.row(*navigation)

    builder.row(
        InlineKeyboardButton(
            text="➕ Додати товар",
            callback_data=f"a:padd:{category_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Категорії", callback_data="a:products"),
        InlineKeyboardButton(text="🏠 Адмін", callback_data="a:home"),
    )
    return builder.as_markup()


def product_actions(product: Product, return_page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Назва", callback_data=f"a:pe:name:{product.id}")
    builder.button(text="🏷 Бренд", callback_data=f"a:pe:brand:{product.id}")
    builder.button(text="💰 Ціна", callback_data=f"a:pe:price:{product.id}")
    builder.button(text="📝 Опис", callback_data=f"a:pe:description:{product.id}")
    builder.button(text="🖼 Фото", callback_data=f"a:pe:photo_file_id:{product.id}")
    builder.button(
        text="⛔ Приховати" if product.in_stock else "✅ Повернути до каталогу",
        callback_data=f"a:ptoggle:{product.id}:{return_page}",
    )
    builder.button(text="🗑 Видалити", callback_data=f"a:pdel:{product.id}:{return_page}")
    builder.button(
        text="◀️ До товарів",
        callback_data=f"a:plist:{product.category_id}:{return_page}",
    )
    builder.adjust(2, 2, 1, 1, 1, 1)
    return builder.as_markup()


def confirm_product_delete(product_id: int, return_page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Так, видалити",
        callback_data=f"a:pdelok:{product_id}:{return_page}",
    )
    builder.button(text="Скасувати", callback_data=f"a:p:{product_id}:{return_page}")
    builder.adjust(1)
    return builder.as_markup()


def settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🏪 Назва магазину", callback_data="a:set:store_name")
    builder.button(text="👋 Привітання", callback_data="a:set:welcome_text")
    builder.button(text="📍 Адреса та графік", callback_data="a:set:address_schedule")
    builder.button(text="💬 Посилання продавця", callback_data="a:set:contact_url")
    builder.button(text="💵 Валюта", callback_data="a:set:currency")
    builder.button(text="🔞 Текст 18+", callback_data="a:set:age_warning")
    builder.button(text="◀️ Адмін-панель", callback_data="a:home")
    builder.adjust(1)
    return builder.as_markup()


def inquiries_list(inquiries: list[Inquiry]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for inquiry in inquiries:
        builder.button(
            text=f"#{inquiry.id} • {inquiry.product_name} • {inquiry.full_name}",
            callback_data=f"a:req:{inquiry.id}",
        )
    builder.button(text="◀️ Адмін-панель", callback_data="a:home")
    builder.adjust(1)
    return builder.as_markup()


def inquiry_actions(inquiry_id: int, user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Написати покупцю", url=f"tg://user?id={user_id}")
    builder.button(text="✅ Опрацьовано", callback_data=f"a:reqdone:{inquiry_id}")
    builder.button(text="◀️ Запити", callback_data="a:reqs")
    builder.adjust(1)
    return builder.as_markup()


def cancel() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Скасувати", callback_data="a:cancel")
    return builder.as_markup()


def photo_step() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Без фото", callback_data="a:photoskip")
    builder.button(text="❌ Скасувати", callback_data="a:cancel")
    builder.adjust(1)
    return builder.as_markup()


def edit_photo(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Видалити фото", callback_data=f"a:photodel:{product_id}")
    builder.button(text="❌ Скасувати", callback_data="a:cancel")
    builder.adjust(1)
    return builder.as_markup()
