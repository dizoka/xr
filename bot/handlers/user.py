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
        self.router.message.register(
            self.order_details_message,
            UserOrderStates.details,
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
        self.router.callback_query.register(self.category, F.data.startswith("u:c:"))
        self.router.callback_query.register(self.product, F.data.startswith("u:p:"))
        self.router.callback_query.register(
            self.order_start, F.data.startswith("u:buy:")
        )
        self.router.callback_query.register(
            self.order_quantity, F.data.startswith("u:qty:")
        )
        self.router.callback_query.register(
            self.order_details_skip, F.data == "u:details:skip"
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


    async def _root_category_name(self, category_id: int) -> str:
        """Повертає назву кореневої категорії для вкладених категорій."""
        current_id: int | None = category_id
        root_name = ""
        for _ in range(12):
            if current_id is None:
                break
            category = await self.catalog.get_category(current_id)
            if category is None:
                break
            root_name = category.name.strip().casefold()
            current_id = category.parent_id
        return root_name

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
            categories = await self.catalog.list_categories()
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
        categories = await self.catalog.list_categories()
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

    async def category(self, callback: CallbackQuery) -> None:
        await answer_callback_safely(callback)
        if not await self._ensure_callback_access(callback) or not callback.message:
            return
        parsed = parse_callback_ints(callback.data, "u:c:", 2)
        if parsed is None:
            await self._show_catalog(callback.message)
            return
        category_id, page = parsed
        category = await self.catalog.get_category(category_id)
        if category is None or not category.active:
            await self._show_catalog(callback.message)
            return

        children = await self.catalog.list_categories(parent_id=category_id)
        is_cartridges = category.name.strip().casefold() in {"картриджі", "картриджи"}
        only_in_stock = not is_cartridges
        total = await self.catalog.count_products(category_id, only_in_stock=only_in_stock)
        total_pages = max(1, math.ceil(total / PRODUCTS_PER_PAGE))
        page = min(max(0, page), total_pages - 1)
        products = await self.catalog.list_products(
            category_id, limit=PRODUCTS_PER_PAGE,
            offset=page * PRODUCTS_PER_PAGE, only_in_stock=only_in_stock
        )
        currency = await self._safe_setting("currency") or "грн"
        cartridges_url = await self._safe_setting("cartridges_url") if is_cartridges else ""
        text = f"<b>{h(category.emoji)} {h(category.name)}</b>\n\nОберіть підкатегорію або товар:"
        if not products and not children:
            text += "\n\nТут поки порожньо."
        await replace_with_text(
            callback.message, text,
            user_kb.category_contents_menu(
                children, products, category_id=category_id, parent_id=category.parent_id,
                page=page, total_pages=total_pages, currency=currency,
                external_catalog_url=cartridges_url
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
        root_category = await self._root_category_name(product.category_id)
        availability_url = ""
        availability_label = ""
        if root_category in {"pod-системи", "pod системи", "pod-системы", "pod systems"}:
            availability_url = await self._safe_setting("colors_url")
            availability_label = "🎨 Переглянути доступні кольори"
        elif root_category in {"рідини", "жидкости", "liquids"}:
            availability_url = await self._safe_setting("flavors_url")
            availability_label = "💧 Переглянути доступні смаки"
        await replace_with_photo_or_text(
            callback.bot,
            callback.message,
            text=product_card_text(product, currency),
            photo_file_id=product.photo_file_id,
            reply_markup=user_kb.product_menu(
                product,
                max(0, return_page),
                contact_url,
                availability_url=availability_url,
                availability_label=availability_label,
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
            await state.set_state(UserOrderStates.details)
            await callback.message.answer(
                "<b>✍️ Деталі товару</b>\n\n"
                "Напишіть одним повідомленням усе потрібне для цього товару:\n"
                "• бажаний колір або смак;\n"
                "• адресу доставки;\n"
                "• бажаний час;\n"
                "• інший коментар.\n\n"
                "Можна написати лише те, що для вас важливо.",
                reply_markup=user_kb.order_details_menu(),
            )
            return
        await state.update_data(quantity=quantity)
        try:
            await callback.message.edit_reply_markup(
                reply_markup=user_kb.quantity_menu(product.id, quantity)
            )
        except Exception:
            logger.debug("Не вдалося оновити клавіатуру кількості", exc_info=True)


    async def order_details_message(self, message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if len(text) > 500:
            await message.answer("Коментар занадто довгий. Максимум 500 символів.")
            return
        await state.update_data(
            variant=text,
            variant_label="Деталі замовлення",
        )
        await self._add_current_item_to_cart(message, state)

    async def order_details_skip(self, callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback, "Без додаткових деталей")
        if not callback.message:
            return
        data = await state.get_data()
        if not data.get("product_id"):
            await callback.message.answer("Цей вибір застарів. Оберіть товар ще раз.")
            return
        await state.update_data(variant="", variant_label="")
        await self._add_current_item_to_cart(callback.message, state)

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

        currency = await self._safe_setting("currency") or "грн"
        total = 0.0
        details_lines: list[str] = []
        for index, item in enumerate(cart, 1):
            quantity = max(1, int(item.get("quantity", 1)))
            try:
                price = float(str(item.get("price", "0")).replace(",", "."))
            except ValueError:
                price = 0.0
            subtotal = price * quantity
            total += subtotal
            details_lines.append(f"{index}. {item.get('title', 'Товар')}")
            details_lines.append(f"Кількість: {quantity}")
            item_details = str(item.get("variant", "")).strip()
            if item_details:
                details_lines.append(f"Деталі: {item_details}")
            details_lines.append(
                f"Сума: {subtotal:g} {currency}"
                if price > 0
                else "Ціна: уточнюється у продавця"
            )
            details_lines.append("")

        request_key = str(data.get("request_key") or uuid4().hex)
        try:
            _, created = await self.inquiries.create_cart_snapshot(
                user_id=callback.from_user.id,
                username=callback.from_user.username,
                full_name=callback.from_user.full_name,
                first_product_id=int(cart[0]["product_id"]),
                item_count=len(cart),
                total_price=f"{total:g}",
                cart_details="\n".join(details_lines).strip(),
                request_key=f"cart:{request_key}",
            )
        except Exception:
            logger.exception("Не вдалося створити одну заявку для кошика")
            await callback.message.answer(
                "Не вдалося оформити замовлення. Спробуйте ще раз трохи пізніше."
            )
            return

        if created:
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
