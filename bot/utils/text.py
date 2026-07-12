from __future__ import annotations

from html import escape

from bot.models import Inquiry, Product
from bot.utils.product_types import order_profile, variant_type_title


def h(value: object) -> str:
    return escape(str(value), quote=False)


def product_title(product: Product) -> str:
    prefix = f"{product.brand} " if product.brand else ""
    return f"{prefix}{product.name}".strip()


def product_card_text(product: Product, currency: str) -> str:
    available = product.in_stock and product.quantity > 0
    status = "✅ Є в наявності" if available else "❌ Немає в наявності"
    description = (
        h(product.description)
        if product.description
        else "Опис товару уточнюйте у продавця."
    )
    return (
        f"<b>{h(product.category_emoji)} {h(product_title(product))}</b>\n\n"
        f"{description}\n\n"
        f"💰 <b>Ціна:</b> {h(product.price)} {h(currency)}\n"
        f"{status}\n\n"
        "🔞 <i>Продаж здійснюється лише повнолітнім. "
        "Продавець може попросити підтвердити вік.</i>"
    )


def admin_product_text(product: Product, currency: str) -> str:
    status = (
        "✅ У наявності"
        if product.in_stock and product.quantity > 0
        else "❌ Немає в наявності"
    )
    photo = "✅ Є" if product.photo_file_id else "— Немає"
    return (
        f"<b>Товар #{product.id}</b>\n\n"
        f"Назва: <b>{h(product.name)}</b>\n"
        f"Бренд: {h(product.brand or '—')}\n"
        f"Категорія: {h(product.category_emoji)} {h(product.category_name)}\n"
        f"Ціна: <b>{h(product.price)} {h(currency)}</b>\n"
        f"Статус: {status}\n"
        f"Кількість: <b>{product.quantity}</b>\n"
        f"Параметр замовлення: <b>{h(variant_type_title(product.variant_type))}</b>\n"
        f"Фото: {photo}\n\n"
        f"Опис:\n{h(product.description or '—')}"
    )


def inquiry_text(inquiry: Inquiry, currency: str) -> str:
    username = f"@{h(inquiry.username)}" if inquiry.username else "не вказано"
    variant_label = inquiry.variant_label.strip() or "Варіант"
    emoji = (
        "🎨"
        if variant_label.casefold() == "колір"
        else "💧"
        if variant_label.casefold() == "смак"
        else "🔹"
    )
    variant_line = (
        f"{emoji} {h(variant_label)}: <b>{h(inquiry.variant)}</b>\n"
        if inquiry.variant
        else ""
    )
    comment_line = (
        f"💬 Коментар: <b>{h(inquiry.comment)}</b>\n" if inquiry.comment else ""
    )
    return (
        f"<b>🛒 Нове замовлення #{inquiry.id}</b>\n\n"
        f"📦 Товар: <b>{h(inquiry.product_name)}</b>\n"
        f"💰 Ціна: <b>{h(inquiry.product_price)} {h(currency)}</b>\n"
        f"{variant_line}"
        f"{comment_line}\n"
        f'👤 Покупець: <a href="tg://user?id={inquiry.user_id}">{h(inquiry.full_name)}</a>\n'
        f"Username: {username}\n"
        f"Telegram ID: <code>{inquiry.user_id}</code>\n"
        f"🕒 Створено: {h(inquiry.created_at)}"
    )


def customer_order_text(product: Product, currency: str, variant: str = "") -> str:
    profile = order_profile(product)
    lines = [
        "<b>✅ Замовлення сформовано</b>",
        "",
        f"📦 {h(profile.product_label)}: <b>{h(product_title(product))}</b>",
        f"💰 Ціна: <b>{h(product.price)} {h(currency)}</b>",
    ]
    if variant and profile.variant_label:
        lines.append(
            f"{profile.variant_emoji or '🔹'} {h(profile.variant_label)}: <b>{h(variant)}</b>"
        )
    lines.extend(
        [
            "",
            "🔞 Продаж здійснюється лише повнолітнім.",
            "",
            "Натисніть кнопку нижче, щоб написати продавцю та уточнити деталі.",
        ]
    )
    return "\n".join(lines)


def cart_text(items: list[dict], currency: str) -> str:
    lines = ["<b>🛒 Ваш кошик</b>", ""]
    total = 0.0
    for index, item in enumerate(items, 1):
        qty = int(item.get("quantity", 1))
        raw_price = str(item.get("price", "0")).replace(",", ".")
        try:
            price = float(raw_price)
        except ValueError:
            price = 0.0
        subtotal = price * qty
        total += subtotal
        lines.append(f"<b>{index}. {h(item.get('title', 'Товар'))}</b>")
        lines.append(f"Кількість: <b>{qty}</b>")
        variant = str(item.get("variant", "")).strip()
        label = str(item.get("variant_label", "")).strip()
        if variant and label:
            lines.append(f"{h(label)}: <b>{h(variant)}</b>")
        lines.append(f"Сума: <b>{subtotal:g} {h(currency)}</b>")
        lines.append("")
    lines.append(f"<b>Разом: {total:g} {h(currency)}</b>")
    lines.append("")
    lines.append("🔞 Продаж здійснюється лише повнолітнім.")
    return "\n".join(lines)


def admin_cart_text(items: list[dict], currency: str, user_id: int, full_name: str, username: str | None) -> str:
    username_text = f"@{h(username)}" if username else "не вказано"
    return (
        "<b>🛒 Нове комплексне замовлення</b>\n\n"
        + cart_text(items, currency)
        + f'\n\n👤 Покупець: <a href="tg://user?id={user_id}">{h(full_name)}</a>'
        + f"\nUsername: {username_text}\nTelegram ID: <code>{user_id}</code>"
    )
