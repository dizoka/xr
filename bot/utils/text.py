from __future__ import annotations

from html import escape

from bot.models import Inquiry, Product


def h(value: object) -> str:
    return escape(str(value), quote=False)


def product_title(product: Product) -> str:
    prefix = f"{product.brand} " if product.brand else ""
    return f"{prefix}{product.name}".strip()


def product_card_text(product: Product, currency: str) -> str:
    status = "✅ У наявності" if product.in_stock else "❌ Немає в наявності"
    description = h(product.description) if product.description else "Опис поки не додано."
    return (
        f"<b>{h(product.category_emoji)} {h(product_title(product))}</b>\n\n"
        f"{description}\n\n"
        f"💰 <b>{h(product.price)} {h(currency)}</b>\n"
        f"{status}\n"
        f"📦 Кількість: <b>{product.quantity}</b>\n\n"
        "🔞 Продаж лише повнолітнім. Продавець може перевірити вік."
    )


def admin_product_text(product: Product, currency: str) -> str:
    status = "✅ У наявності" if product.in_stock else "⛔ Приховано з каталогу"
    photo = "✅ Є" if product.photo_file_id else "— Немає"
    return (
        f"<b>Товар #{product.id}</b>\n\n"
        f"Назва: <b>{h(product.name)}</b>\n"
        f"Бренд: {h(product.brand or '—')}\n"
        f"Категорія: {h(product.category_emoji)} {h(product.category_name)}\n"
        f"Ціна: <b>{h(product.price)} {h(currency)}</b>\n"
        f"Статус: {status}\n"
        f"Кількість: <b>{product.quantity}</b>\n"
        f"Фото: {photo}\n\n"
        f"Опис:\n{h(product.description or '—')}"
    )


def inquiry_text(inquiry: Inquiry, currency: str) -> str:
    username = f"@{h(inquiry.username)}" if inquiry.username else "не вказано"
    return (
        f"<b>Новий запит #{inquiry.id}</b>\n\n"
        f"Товар: <b>{h(inquiry.product_name)}</b>\n"
        f"Ціна: {h(inquiry.product_price)} {h(currency)}\n"
        f"Варіант: <b>{h(inquiry.variant or '—')}</b>\n"
        f"Коментар: {h(inquiry.comment or '—')}\n\n"
        f"Покупець: <a href=\"tg://user?id={inquiry.user_id}\">{h(inquiry.full_name)}</a>\n"
        f"Username: {username}\n"
        f"Telegram ID: <code>{inquiry.user_id}</code>\n"
        f"Створено: {h(inquiry.created_at)}"
    )
