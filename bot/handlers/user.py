from __future__ import annotations

import logging
import math

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.core.constants import DEFAULT_SETTINGS, PRODUCTS_PER_PAGE
from bot.keyboards import admin as admin_kb
from bot.keyboards import user as user_kb
from bot.repositories.catalog_repository import CatalogRepository
from bot.repositories.inquiry_repository import InquiryRepository
from bot.states.user import UserOrderStates, UserSearchStates
from bot.utils.callbacks import (
    CallbackErrorMiddleware,
    answer_callback_safely,
    parse_callback_ints,
)
from bot.utils.messages import replace_with_photo_or_text, replace_with_text
from bot.utils.text import h, inquiry_text, product_card_text, product_title


class UserHandlers:
    """Реєструє та обробляє всі дії покупців у боті."""

    def __init__(
        self,
        catalog: CatalogRepository,
        inquiries: InquiryRepository,
        admin_ids: frozenset[int],
    ) -> None:
        self.catalog = catalog
        self.inquiries = inquiries
        self.admin_ids = admin_ids
        self._session_age_confirmations: set[int] = set()
        self.router = Router(name="user")
        self.router.callback_query.middleware(CallbackErrorMiddleware())
        self._register()

    def _register(self) -> None:
        self.router.message.register(self.start, CommandStart())
        self.router.message.register(self.catalog_command, Command("catalog"))
        self.router.message.register(self.show_id, Command("id"))
        self.router.message.register(
            self.search_message,
            UserSearchStates.query,
            F.text,
            ~F.text.startswith("/"),
        )
        self.router.message.register(
            self.order_variant_message,
            UserOrderStates.variant,
            F.text,
            ~F.text.startswith("/"),
        )
        self.router.message.register(
            self.order_comment_message,
            UserOrderStates.comment,
            F.text,
            ~F.text.startswith("/"),
        )

        self.router.callback_query.register(self.noop, F.data == "noop")
        self.router.callback_query.register(self.age_yes, F.data == "age:yes")
        self.router.callback_query.register(self.age_no, F.data == "age:no")
        self.router.callback_query.register(self.home, F.data == "u:home")
        self.router.callback_query.register(self.catalog_callback, F.data == "u:catalog")
        self.router.callback_query.register(self.info, F.data == "u:info")
        self.router.callback_query.register(self.search_start, F.data == "u:search")
        self.router.callback_query.register(self.category, F.data.startswith("u:c:"))
        self.router.callback_query.register(self.product, F.data.startswith("u:p:"))
        self.router.callback_query.register(self.order_start, F.data.startswith("u:buy:"))
        self.router.callback_query.register(self.order_skip_comment, F.data == "u:order:skip")
        self.router.callback_query.register(self.order_cancel, F.data == "u:order:cancel")
        # Резервний обробник: жодна стара або помилкова кнопка u:* не зависає.
        self.router.callback_query.register(self.unknown_user_button, F.data.startswith("u:"))

    async def _safe_setting(self, key: str) -> str:
        default = DEFAULT_SETTINGS.get(key, "")
        try:
            return await self.catalog.get_setting(key, default)
        except Exception:
            logging.exception("Не вдалося отримати налаштування %s", key)
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
            logging.exception("Не вдалося завантажити категорії")
            await replace_with_text(
                message,
                "<b>🛍 Каталог</b>\n\nНе вдалося завантажити категорії. Спробуйте ще раз.",
                user_kb.fallback_menu(),
            )
            return

        promotions_url = await self._safe_setting("promotions_url")
        text = "<b>🛍 Каталог</b>\n\nОберіть категорію:"
        if not categories:
            text += "\n\nКатегорії поки не додані."
        await replace_with_text(
            message,
            text,
            user_kb.categories_menu(categories, promotions_url),
        )

    async def _show_age_gate(self, message: Message) -> None:
        warning = await self._safe_setting("age_warning")
        await message.answer(h(warning), reply_markup=user_kb.age_confirmation())

    async def _replace_with_age_gate(self, message: Message) -> None:
        warning = await self._safe_setting("age_warning")
        await replace_with_text(message, h(warning), user_kb.age_confirmation())

    async def _has_access(self, user_id: int) -> bool:
        if user_id in self._session_age_confirmations:
            return True
        try:
            confirmed = await self.catalog.is_age_confirmed(user_id)
        except Exception:
            logging.exception("Не вдалося перевірити підтвердження віку user_id=%s", user_id)
            return False
        if confirmed:
            self._session_age_confirmations.add(user_id)
        return confirmed

    async def _ensure_callback_access(self, callback: CallbackQuery) -> bool:
        if await self._has_access(callback.from_user.id):
            return True
        if callback.message:
            await self._replace_with_age_gate(callback.message)
        return False

    async def start(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        if not await self._has_access(message.from_user.id):
            await self._show_age_gate(message)
            return
        text, contact_url = await self._home_text()
        await message.answer(text, reply_markup=user_kb.main_menu(contact_url))

    async def show_id(self, message: Message) -> None:
        await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")

    async def catalog_command(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        if not await self._has_access(message.from_user.id):
            await self._show_age_gate(message)
            return
        try:
            categories = await self.catalog.list_categories()
        except Exception:
            logging.exception("Не вдалося завантажити каталог за командою /catalog")
            await message.answer(
                "<b>🛍 Каталог</b>\n\nНе вдалося завантажити категорії. Спробуйте ще раз.",
                reply_markup=user_kb.fallback_menu(),
            )
            return
        promotions_url = await self._safe_setting("promotions_url")
        await message.answer(
            "<b>🛍 Каталог</b>\n\nОберіть категорію:",
            reply_markup=user_kb.categories_menu(categories, promotions_url),
        )

    async def noop(self, callback: CallbackQuery) -> None:
        await answer_callback_safely(callback)

    async def age_yes(self, callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        await state.clear()

        user_id = callback.from_user.id
        self._session_age_confirmations.add(user_id)
        try:
            await self.catalog.confirm_age(user_id)
        except Exception:
            logging.exception("Не вдалося зберегти підтвердження віку user_id=%s", user_id)

        if callback.message:
            await self._show_catalog(callback.message)

    async def age_no(self, callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(callback)
        await state.clear()
        if callback.message:
            await replace_with_text(
                callback.message,
                "Доступ до каталогу закрито. Повертайтеся після досягнення повноліття.",
            )

    async def home(self, callback: CallbackQuery, state: FSMContext) -> None:
        # Відповідаємо Telegram одразу, щоб кнопка не зависала після сну Render.
        await answer_callback_safely(callback)
        await state.clear()
        if not await self._ensure_callback_access(callback):
            return
        if callback.message:
            await self._show_home(callback.message)

    async def catalog_callback(self, callback: CallbackQuery) -> None:
        await answer_callback_safely(callback)
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
        if not await self._ensure_callback_access(callback):
            return
        if not callback.message:
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

        total = await self.catalog.count_products(category_id, only_in_stock=True)
        total_pages = max(1, math.ceil(total / PRODUCTS_PER_PAGE))
        page = min(page, total_pages - 1)
        products = await self.catalog.list_products(
            category_id,
            limit=PRODUCTS_PER_PAGE,
            offset=page * PRODUCTS_PER_PAGE,
            only_in_stock=True,
        )
        currency = await self._safe_setting("currency") or "грн"
        empty_text = "\n\nУ цій категорії поки немає доступних товарів." if not products else ""
        text = f"<b>{h(category.emoji)} {h(category.name)}</b>{empty_text}\n\nОберіть товар:"
        await replace_with_text(
            callback.message,
            text,
            user_kb.products_menu(
                products,
                category_id=category_id,
                page=page,
                total_pages=total_pages,
                currency=currency,
            ),
        )

    async def product(self, callback: CallbackQuery, bot: Bot) -> None:
        await answer_callback_safely(callback)
        if not await self._ensure_callback_access(callback):
            return
        if not callback.message:
            return

        parsed = parse_callback_ints(callback.data, "u:p:", 2)
        if parsed is None:
            await self._show_catalog(callback.message)
            return
        product_id, return_page = parsed
        return_page = max(0, return_page)

        product = await self.catalog.get_product(product_id)
        if product is None or not product.in_stock:
            await self._show_catalog(callback.message)
            return

        currency = await self._safe_setting("currency") or "грн"
        await replace_with_photo_or_text(
            bot,
            callback.message,
            text=product_card_text(product, currency),
            photo_file_id=product.photo_file_id,
            reply_markup=user_kb.product_menu(product, return_page),
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
        if not await self._has_access(message.from_user.id):
            await state.clear()
            await self._show_age_gate(message)
            return

        query = (message.text or "").strip()
        if len(query) < 2:
            await message.answer("Введіть щонайменше 2 символи.")
            return

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

    @staticmethod
    def _variant_label(product) -> tuple[str, str]:
        variant_type = (product.variant_type or "none").strip().casefold()
        category = product.category_name.strip().casefold()
        if variant_type == "none":
            if "рід" in category or "жид" in category:
                variant_type = "flavor"
            elif "pod" in category or "систем" in category:
                variant_type = "color"
        labels = {
            "flavor": ("смак", "Напишіть бажаний смак одним повідомленням."),
            "color": ("колір", "Напишіть бажаний колір одним повідомленням."),
            "strength": ("міцність", "Напишіть бажану міцність одним повідомленням."),
            "other": ("варіант", "Напишіть бажаний варіант одним повідомленням."),
        }
        return labels.get(variant_type, ("варіант", "Напишіть потрібний варіант одним повідомленням."))

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
        label, prompt = self._variant_label(product)
        await state.set_state(UserOrderStates.variant)
        await state.update_data(product_id=product.id, variant_label=label)
        await callback.message.answer(
            f"<b>🛒 {h(product_title(product))}</b>\n\n{h(prompt)}\n\n"
            "Наприклад: <i>Зелене яблуко</i> або <i>Чорний</i>.",
            reply_markup=user_kb.order_cancel_menu(),
        )

    async def order_variant_message(self, message: Message, state: FSMContext) -> None:
        value = (message.text or "").strip()
        if len(value) < 1 or len(value) > 120:
            await message.answer("Напишіть короткий варіант до 120 символів.")
            return
        await state.update_data(variant=value)
        await state.set_state(UserOrderStates.comment)
        await message.answer(
            "Додайте коментар до замовлення або натисніть «Без коментаря».\n\n"
            "Наприклад: <i>Заберу сьогодні після 18:00</i>.",
            reply_markup=user_kb.order_comment_menu(),
        )

    async def _finish_order(
        self,
        message: Message,
        state: FSMContext,
        bot: Bot,
        comment: str,
        customer: User,
    ) -> None:
        data = await state.get_data()
        product_id = int(data.get("product_id", 0))
        variant = str(data.get("variant", "")).strip()
        product = await self.catalog.get_product(product_id)
        if product is None or not product.in_stock:
            await state.clear()
            await message.answer("Цей товар уже недоступний.", reply_markup=user_kb.back_home())
            return
        inquiry_id, _ = await self.inquiries.create(
            user_id=customer.id,
            username=customer.username,
            full_name=customer.full_name,
            product_id=product_id,
            variant=variant,
            comment=comment.strip(),
        )
        inquiry = await self.inquiries.get(inquiry_id)
        await state.clear()
        if inquiry is not None:
            currency = await self._safe_setting("currency") or "грн"
            staff_ids = await self.catalog.list_staff_admins()
            recipients = set(self.admin_ids) | set(staff_ids)
            for admin_id in recipients:
                try:
                    await bot.send_message(
                        admin_id,
                        inquiry_text(inquiry, currency),
                        reply_markup=admin_kb.inquiry_actions(inquiry.id, inquiry.user_id),
                    )
                except (TelegramBadRequest, TelegramForbiddenError):
                    logging.exception("Не вдалося повідомити адміністратора %s", admin_id)
        await message.answer(
            "✅ <b>Заявку надіслано продавцю.</b>\n\n"
            f"Товар: {h(product_title(product))}\n"
            f"Ваш варіант: <b>{h(variant)}</b>\n\n"
            "Продавець зв’яжеться з вами для підтвердження.",
            reply_markup=user_kb.back_home(),
        )

    async def order_comment_message(self, message: Message, state: FSMContext, bot: Bot) -> None:
        comment = (message.text or "").strip()
        if len(comment) > 500:
            await message.answer("Коментар має містити до 500 символів.")
            return
        await self._finish_order(message, state, bot, comment, message.from_user)

    async def order_skip_comment(self, callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        await answer_callback_safely(callback)
        if callback.message:
            await self._finish_order(callback.message, state, bot, "", callback.from_user)

    async def order_cancel(self, callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await answer_callback_safely(callback, "Замовлення скасовано")
        if callback.message:
            await self._show_home(callback.message)

