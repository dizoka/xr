from __future__ import annotations

import logging
import math
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.core.constants import DEFAULT_SETTINGS, PRODUCTS_PER_PAGE
from bot.keyboards import admin as admin_kb
from bot.keyboards import user as user_kb
from bot.middlewares.rate_limit import RateLimitMiddleware
from bot.repositories.catalog_repository import CatalogRepository
from bot.repositories.inquiry_repository import InquiryRepository
from bot.services import (
    DuplicateOrderError,
    NotificationService,
    OrderService,
    ProductUnavailableError,
)
from bot.states.user import UserOrderStates, UserSearchStates
from bot.utils.callbacks import (
    CallbackErrorMiddleware,
    answer_callback_safely,
    parse_callback_ints,
)
from bot.utils.messages import replace_with_photo_or_text, replace_with_text
from bot.utils.text import (
    admin_cart_text,
    cart_text,
    h,
    product_card_text,
    product_title,
)
from bot.utils.ttl_cache import TTLCache


logger = logging.getLogger(__name__)


class UserHandlers:
    """Реєструє та обробляє всі дії покупців у боті."""

    def __init__(
        self,
        catalog: CatalogRepository,
        inquiries: InquiryRepository,
        admin_ids: frozenset[int],
        bot: Bot | None = None,
    ) -> None:
        self.catalog = catalog
        self.inquiries = inquiries
        self.admin_ids = admin_ids
        # ``bot`` лишено необов'язковим для сумісності зі старим main.py.
        # У самих handlers використовуємо bot, прив'язаний до поточного update.
        self.bot = bot
        self.order_service = OrderService(catalog, inquiries)
        self._age_cache = TTLCache[int](ttl_seconds=15 * 60, max_size=5_000)
        self.router = Router(name="user")
        self.router.message.middleware(RateLimitMiddleware(limit=8, period=5))
        self.router.callback_query.middleware(RateLimitMiddleware(limit=12, period=5))
        self.router.callback_query.middleware(CallbackErrorMiddleware())
        self._register()

    def _register(self) -> None:
        self.router.message.register(self.start, CommandStart())
        self.router.message.register(self.catalog_command, Command("catalog"))
        self.router.message.register(self.help_command, Command("help"))
        self.router.message.register(self.show_id, Command("id"))
        self.router.message.register(
            self.search_message,
            UserSearchStates.query,
            F.text,
            ~F.text.startswith("/"),
        )

        self.router.callback_query.register(self.noop, F.data == "noop")
        self.router.callback_query.register(self.age_yes, F.data == "age:yes")
        self.router.callback_query.register(self.age_no, F.data == "age:no")
        self.router.callback_query.register(self.home, F.data == "u:home")
        self.router.callback_query.register(
            self.catalog_callback, F.data == "u:catalog"
        )
        self.router.callback_query.register(self.info, F.data == "u:info")
        self.router.callback_query.register(self.search_start, F.data == "u:search")
        self.router.callback_query.register(self.liquids_menu, F.data == "u:liquids")
        self.router.callback_query.register(self.liquid_category, F.data.startswith("u:liq:"))
        self.router.callback_query.register(self.category, F.data.startswith("u:c:"))
        self.router.callback_query.register(self.product, F.data.startswith("u:p:"))
        self.router.callback_query.register(
            self.order_start, F.data.startswith("u:buy:")
        )
        self.router.callback_query.register(
            self.order_quantity, F.data.startswith("u:qty:")
        )
        self.router.callback_query.register(
            self.cart_add_more, F.data == "u:cart:add"
        )
        self.router.callback_query.register(
            self.cart_checkout, F.data == "u:cart:checkout"
        )
        self.router.callback_query.register(
            self.cart_clear, F.data == "u:cart:clear"
        )
        self.router.callback_query.register(
            self.order_cancel, F.data == "u:order:cancel"
        )
        self.router.callback_query.register(
            self.unknown_user_button, F.data.startswith("u:")
        )

    async def _safe_setting(self, key: str) -> str:
        default = DEFAULT_SETTINGS.get(key, "")
        try:
            return await self.catalog.get_setting(key, default)
        except Exception:
            logger.exception("Не вдалося отримати налаштування %s", key)
            return default

    async def _home_text(self) -> tuple[str, str]:
        store_name = await self._safe_setting("store_name")
        welcome_text = await self._safe_setting("welcome_text")
        contact_url = await self._safe_setting("contact_url")
        text = f"<b>💎 {h(store_name)}</b>\n\n{h(welcome_text)}"
        return text, contact_url

    async def _show_home(self, message: Message) -> None:
        text, contact_url = await self._home_text()
        await replace_with_text(message, text, user_kb.main_menu(contact_url))

    async def _show_catalog(self, message: Message) -> None:
        try:
            categories = await self.catalog.list_customer_categories()
        except Exception:
            logger.exception("Не вдалося завантажити категорії")
            await replace_with_text(
                message,
                "<b>🛍 Каталог</b>\n\nНе вдалося завантажити категорії. Спробуйте ще раз.",
                user_kb.fallback_menu(),
            )
            return

        promotions_url = await self._safe_setting("promotions_url")
        cartridges_url = await self._safe_setting("cartridges_url")
        text = "<b>🛍 Каталог</b>\n\nОберіть категорію:"
        if not categories:
            text += "\n\nКатегорії поки не додані."
        await replace_with_text(
            message,
            text,
            user_kb.categories_menu(categories, promotions_url, cartridges_url),
        )

    async def _show_age_gate(self, message: Message) -> None:
        warning = await self._safe_setting("age_warning")
        await message.answer(h(warning), reply_markup=user_kb.age_confirmation())

    async def _replace_with_age_gate(self, message: Message) -> None:
        warning = await self._safe_setting("age_warning")
        await replace_with_text(message, h(warning), user_kb.age_confirmation())

    async def _has_access(self, user_id: int) -> bool:
        if self._age_cache.contains(user_id):
            return True
        try:
            confirmed = await self.catalog.is_age_confirmed(user_id)
        except Exception:
            logger.exception(
                "Не вдалося перевірити підтвердження віку user_id=%s", user_id
            )
            return False
        if confirmed:
            self._age_cache.add(user_id)
        return confirmed

    async def _ensure_callback_access(self, callback: CallbackQuery) -> bool:
        if await self._has_access(callback.from_user.id):
            return True
        if callback.message:
            await self._replace_with_age_gate(callback.message)
        return False

    async def start(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        if message.from_user is None:
            return
        if not await self._has_access(message.from_user.id):
            await self._show_age_gate(message)
            return
        text, contact_url = await self._home_text()
        await message.answer(text, reply_markup=user_kb.main_menu(contact_url))

    async def help_command(self, message: Message) -> None:
        await message.answer(
            "<b>❓ Допомога</b>\n\n"
            "🛍 /catalog — відкрити каталог\n"
            "🔎 Пошук доступний у головному меню\n"
            "🆔 /id — показати ваш Telegram ID\n"
            "🏠 /start — повернутися на головну\n\n"
            "Щоб замовити товар, відкрийте його картку та натисніть "
            "«🛒 Обрати товар»."
        )

    async def show_id(self, message: Message) -> None:
        if message.from_user:
            await message.answer(
                f"Ваш Telegram ID: <code>{message.from_user.id}</code>"
            )

    async def catalog_command(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        if message.from_user is None:
            return
        if not await self._has_access(message.from_user.id):
            await self._show_age_gate(message)
            return
        categories = await self.catalog.list_customer_categories()
        promotions_url = await self._safe_setting("promotions_url")
        cartridges_url = await self._safe_setting("cartridges_url")
        await message.answer(
            "<b>🛍 Каталог</b>\n\nОберіть категорію:",
            reply_markup=user_kb.categories_menu(
                categories,
                promotions_url,
                cartridges_url,
            ),
        )

    async def noop(self, callback: CallbackQuery) -> None:
        await answer_callback_safely(callback)

    async def age_yes(self, callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        await state.clear()
        user_id = callback.from_user.id
        self._age_cache.add(user_id)
        try:
            await self.catalog.confirm_age(user_id)
        except Exception:
            logger.exception(
                "Не вдалося зберегти підтвердження віку user_id=%s", user_id
            )
        if callback.message:
            await self._show_catalog(callback.message)

    async def age_no(self, callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        await state.clear()
        self._age_cache.discard(callback.from_user.id)
        if callback.message:
            await replace_with_text(
                callback.message,
                "Доступ до каталогу закрито. Повертайтеся після досягнення повноліття.",
            )

    async def home(self, callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        await state.clear()
        if not await self._ensure_callback_access(callback):
            return
        if callback.message:
            await self._show_home(callback.message)

    async def catalog_callback(
        self, callback: CallbackQuery, state: FSMContext
    ) -> None:
        await answer_callback_safely(callback)
        await state.clear()
        if not await self._ensure_callback_access(callback):
            return
        if callback.message:
            await self._show_catalog(callback.message)

    async def info(self, callback: CallbackQuery) -> None:
        await answer_callback_safely(callback)
        if not await self._ensure_callback_access(callback):
            return
        address = await self._safe_setting("address_schedule")
        if callback.message:
            await replace_with_text(
                callback.message,
                f"<b>📍 Адреса та графік</b>\n\n{h(address)}",
                user_kb.back_home(),
            )

    async def liquids_menu(self, callback: CallbackQuery) -> None:
        await answer_callback_safely(callback)
        if not await self._ensure_callback_access(callback) or not callback.message:
            return
        categories = await self.catalog.list_liquid_volume_categories()
        text = (
            "<b>💧 Рідини</b>\n\n"
            "Оберіть потрібний об’єм:"
        )
        await replace_with_text(
            callback.message,
            text,
            user_kb.liquid_volumes_menu(categories),
        )

    async def liquid_category(self, callback: CallbackQuery) -> None:
        await answer_callback_safely(callback)
        if not await self._ensure_callback_access(callback) or not callback.message:
            return
        parsed = parse_callback_ints(callback.data, "u:liq:", 2)
        if parsed is None:
            await self.liquids_menu(callback)
            return
        category_id, page = parsed
        category = await self.catalog.get_category(category_id)
        if category is None or not category.active:
            await self.liquids_menu(callback)
            return
        page = max(0, page)
        total = await self.catalog.count_products(category_id, only_in_stock=False)
        total_pages = max(1, math.ceil(total / PRODUCTS_PER_PAGE))
        page = min(page, total_pages - 1)
        products = await self.catalog.list_products(
            category_id,
            limit=PRODUCTS_PER_PAGE,
            offset=page * PRODUCTS_PER_PAGE,
            only_in_stock=False,
        )
        currency = await self._safe_setting("currency") or "грн"
        volume = next((v for v in ("30", "15", "10") if v in category.name), "")
        text = (
            f"<b>💧 Рідини {h(volume)} мл</b>\n\n"
            "Оберіть рідину нижче. Смаки уточнюйте у продавця."
        )
        await replace_with_text(
            callback.message,
            text,
            user_kb.products_menu(
                products,
                category_id=category_id,
                page=page,
                total_pages=total_pages,
                currency=currency,
                back_callback="u:liquids",
                back_text="◀️ Об’єм рідини",
                page_callback_prefix="u:liq",
            ),
        )

    async def category(self, callback: CallbackQuery) -> None:
        await answer_callback_safely(callback)
        if not await self._ensure_callback_access(callback) or not callback.message:
            return

        parsed = parse_callback_ints(callback.data, "u:c:", 2)
        if parsed is None:
            await self._show_catalog(callback.message)
            return
        category_id, page = parsed
        page = max(0, page)

        category = await self.catalog.get_category(category_id)
        if category is None or not category.active:
            await self._show_catalog(callback.message)
            return

        if category.name.strip().casefold() in {"рідини", "жидкости", "liquids"}:
            categories = await self.catalog.list_liquid_volume_categories()
            await replace_with_text(
                callback.message,
                "<b>💧 Рідини</b>\n\nОберіть потрібний об’єм:",
                user_kb.liquid_volumes_menu(categories),
            )
            return

        is_cartridges = category.name.strip().casefold() in {"картриджі", "картриджи"}
        # Для картриджів показуємо також позиції, яких зараз немає,
        # щоб покупець бачив повний асортимент. Купити їх неможливо,
        # доки продавець не перемкне статус на «Є в наявності».
        only_in_stock = not is_cartridges
        total = await self.catalog.count_products(category_id, only_in_stock=only_in_stock)
        total_pages = max(1, math.ceil(total / PRODUCTS_PER_PAGE))
        page = min(page, total_pages - 1)
        products = await self.catalog.list_products(
            category_id,
            limit=PRODUCTS_PER_PAGE,
            offset=page * PRODUCTS_PER_PAGE,
            only_in_stock=only_in_stock,
        )
        currency = await self._safe_setting("currency") or "грн"
        cartridges_url = (
            await self._safe_setting("cartridges_url") if is_cartridges else ""
        )
        empty_text = (
            "\n\nУ цій категорії поки немає товарів для додавання в кошик."
            if not products
            else ""
        )
        extra_hint = (
            "\n\nОберіть картридж нижче, щоб додати його в кошик."
            if is_cartridges
            else "\n\nОберіть товар:"
        )
        text = f"<b>{h(category.emoji)} {h(category.name)}</b>{empty_text}{extra_hint}"
        await replace_with_text(
            callback.message,
            text,
            user_kb.products_menu(
                products,
                category_id=category_id,
                page=page,
                total_pages=total_pages,
                currency=currency,
                external_catalog_url=cartridges_url,
            ),
        )

    async def product(self, callback: CallbackQuery) -> None:
        await answer_callback_safely(callback)
        if not await self._ensure_callback_access(callback) or not callback.message:
            return

        parsed = parse_callback_ints(callback.data, "u:p:", 2)
        if parsed is None:
            await self._show_catalog(callback.message)
            return
        product_id, return_page = parsed
        product = await self.catalog.get_product(product_id)
        if product is None:
            await self._show_catalog(callback.message)
            return

        currency = await self._safe_setting("currency") or "грн"
        contact_url = await self._safe_setting("contact_url")
        await replace_with_photo_or_text(
            callback.bot,
            callback.message,
            text=product_card_text(product, currency),
            photo_file_id=product.photo_file_id,
            reply_markup=user_kb.product_menu(
                product,
                max(0, return_page),
                contact_url,
                back_callback_prefix=(
                    "u:liq"
                    if product.category_name.strip().casefold().startswith(("рідини ", "жидкости "))
                    else "u:c"
                ),
            ),
        )

    async def search_start(self, callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        if not await self._ensure_callback_access(callback):
            await state.clear()
            return
        await state.set_state(UserSearchStates.query)
        if callback.message:
            await replace_with_text(
                callback.message,
                "<b>🔎 Пошук товару</b>\n\nВведіть назву моделі або бренд одним повідомленням.",
                user_kb.back_home(),
            )

    async def search_message(self, message: Message, state: FSMContext) -> None:
        if message.from_user is None:
            return
        if not await self._has_access(message.from_user.id):
            await state.clear()
            await self._show_age_gate(message)
            return

        query = (message.text or "").strip()
        if len(query) < 2:
            await message.answer("Введіть щонайменше 2 символи.")
            return

        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        products = await self.catalog.search_products(query)
        currency = await self._safe_setting("currency") or "грн"
        await state.clear()
        if not products:
            await message.answer(
                f"За запитом <b>{h(query)}</b> нічого не знайдено.",
                reply_markup=user_kb.search_results([], currency),
            )
            return

        await message.answer(
            f"<b>Результати пошуку: {h(query)}</b>\n\nЗнайдено: {len(products)}",
            reply_markup=user_kb.search_results(products, currency),
        )

    async def order_start(self, callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        if not await self._ensure_callback_access(callback):
            return
        parsed = parse_callback_ints(callback.data, "u:buy:", 1)
        if parsed is None or not callback.message:
            return

        product = await self.catalog.get_product(parsed[0])
        if product is None or not product.in_stock:
            await callback.message.answer("Цей товар зараз недоступний.")
            return

        existing = await state.get_data()
        cart = list(existing.get("cart", []))
        await state.set_state(UserOrderStates.quantity)
        await state.update_data(
            cart=cart,
            product_id=product.id,
            quantity=1,
            variant_label="",
            variant="",
            request_key=uuid4().hex,
        )
        await callback.message.answer(
            f"<b>🛒 {h(product_title(product))}</b>\n\nОберіть потрібну кількість:",
            reply_markup=user_kb.quantity_menu(product.id, 1),
        )

    async def order_quantity(self, callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        if not callback.message:
            return
        parts = (callback.data or "").split(":")
        if len(parts) != 4:
            return
        action = parts[2]
        try:
            product_id = int(parts[3])
        except ValueError:
            return
        data = await state.get_data()
        if int(data.get("product_id", 0)) != product_id:
            await callback.message.answer("Цей вибір застарів. Оберіть товар ще раз.")
            return
        product = await self.catalog.get_product(product_id)
        if product is None or not product.in_stock:
            await state.clear()
            await callback.message.answer("Цей товар уже недоступний.")
            return
        quantity = max(1, int(data.get("quantity", 1)))
        if action == "plus":
            quantity = min(999, quantity + 1)
        elif action == "minus":
            quantity = max(1, quantity - 1)
        elif action == "confirm":
            await state.update_data(quantity=quantity, variant="", variant_label="")
            await self._add_current_item_to_cart(callback.message, state)
            return
        await state.update_data(quantity=quantity)
        try:
            await callback.message.edit_reply_markup(
                reply_markup=user_kb.quantity_menu(product.id, quantity)
            )
        except Exception:
            logger.debug("Не вдалося оновити клавіатуру кількості", exc_info=True)

    async def _add_current_item_to_cart(self, message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        product_id = int(data.get("product_id", 0))
        product = await self.catalog.get_product(product_id)
        if product is None or not product.in_stock:
            await message.answer("Цей товар уже недоступний.")
            return
        quantity = max(1, min(int(data.get("quantity", 1)), 999))
        cart = list(data.get("cart", []))
        cart.append({
            "product_id": product.id,
            "title": product_title(product),
            "price": product.price,
            "quantity": quantity,
            "variant": str(data.get("variant", "")).strip(),
            "variant_label": str(data.get("variant_label", "")).strip(),
        })
        await state.set_state(UserOrderStates.cart)
        await state.update_data(cart=cart, product_id=0, quantity=1, variant="", variant_label="")
        currency = await self._safe_setting("currency") or "грн"
        contact_url = await self._safe_setting("contact_url")
        await message.answer(
            cart_text(cart, currency),
            reply_markup=user_kb.cart_menu(contact_url),
        )

    async def cart_add_more(self, callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        if callback.message:
            await self._show_catalog(callback.message)

    async def cart_clear(self, callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback, "Кошик очищено")
        await state.clear()
        if callback.message:
            await self._show_catalog(callback.message)

    async def cart_checkout(self, callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        if not callback.message:
            return
        data = await state.get_data()
        cart = list(data.get("cart", []))
        if not cart:
            await callback.message.answer("Кошик порожній.", reply_markup=user_kb.back_home())
            return

        created_any = False
        for index, item in enumerate(cart):
            try:
                await self.order_service.create_order(
                    user_id=callback.from_user.id,
                    username=callback.from_user.username,
                    full_name=callback.from_user.full_name,
                    product_id=int(item["product_id"]),
                    variant_label=str(item.get("variant_label", "")),
                    variant=str(item.get("variant", "")),
                    request_key=f"{data.get('request_key') or uuid4().hex}:{index}:{item.get('quantity', 1)}",
                )
                created_any = True
            except (ProductUnavailableError, DuplicateOrderError):
                logger.warning("Не вдалося додати позицію кошика: %s", item)

        currency = await self._safe_setting("currency") or "грн"
        if created_any:
            staff_ids = await self.catalog.list_staff_admins()
            recipients = set(self.admin_ids) | set(staff_ids)
            await NotificationService(callback.bot).send_many(
                recipients,
                admin_cart_text(
                    cart, currency, callback.from_user.id,
                    callback.from_user.full_name, callback.from_user.username
                ),
            )
        await state.clear()
        contact_url = await self._safe_setting("contact_url")
        await callback.message.answer(
            "<b>✅ Замовлення сформовано</b>\n\n" + cart_text(cart, currency),
            reply_markup=user_kb.order_ready_menu(contact_url),
        )

    async def unknown_user_button(
        self, callback: CallbackQuery, state: FSMContext
    ) -> None:
        await answer_callback_safely(
            callback,
            "Кнопку оновлено. Відкриваю головне меню.",
        )
        await state.clear()
        if not await self._ensure_callback_access(callback):
            return
        if callback.message:
            await self._show_home(callback.message)

    async def order_cancel(self, callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await answer_callback_safely(callback, "Замовлення скасовано")
        if callback.message:
            await self._show_home(callback.message)
