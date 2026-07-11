from __future__ import annotations

import logging
import math

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.core.constants import PRODUCTS_PER_PAGE
from bot.keyboards import admin as admin_kb
from bot.keyboards import user as user_kb
from bot.repositories.catalog_repository import CatalogRepository
from bot.repositories.inquiry_repository import InquiryRepository
from bot.states.user import UserSearchStates
from bot.utils.messages import replace_with_photo_or_text, replace_with_text
from bot.utils.text import h, inquiry_text, product_card_text


class UserHandlers:
    """Реєструє та обробляє всі дії користувачів у боті."""

    def __init__(
        self,
        catalog: CatalogRepository,
        inquiries: InquiryRepository,
        admin_ids: frozenset[int],
    ) -> None:
        self.catalog = catalog
        self.inquiries = inquiries
        self.admin_ids = admin_ids
        # Швидкий резерв на поточний запуск. Основне підтвердження все одно
        # зберігається в Turso, але ця множина не дає кнопці «зависнути»,
        # якщо база тимчасово прокидається або відповідає повільно.
        self._session_age_confirmations: set[int] = set()
        self.router = Router(name="user")
        self._register()

    def _register(self) -> None:
        self.router.message.register(self.start, CommandStart())
        self.router.message.register(self.catalog_command, Command("catalog"))
        self.router.message.register(self.search_message, UserSearchStates.query, F.text)

        self.router.callback_query.register(self.noop, F.data == "noop")
        self.router.callback_query.register(self.age_yes, F.data == "age:yes")
        self.router.callback_query.register(self.age_no, F.data == "age:no")
        self.router.callback_query.register(self.home, F.data == "u:home")
        self.router.callback_query.register(self.catalog_callback, F.data == "u:catalog")
        self.router.callback_query.register(self.info, F.data == "u:info")
        self.router.callback_query.register(self.search_start, F.data == "u:search")
        self.router.callback_query.register(self.category, F.data.startswith("u:c:"))
        self.router.callback_query.register(self.product, F.data.startswith("u:p:"))
        self.router.callback_query.register(self.inquiry, F.data.startswith("u:q:"))

    async def _home_text(self) -> tuple[str, str]:
        settings = await self.catalog.get_all_settings()
        store_name = settings.get("store_name", "CrystalStore")
        welcome_text = settings.get("welcome_text", "Оберіть розділ нижче.")
        contact_url = settings.get("contact_url", "")
        text = f"<b>💎 {h(store_name)}</b>\n\n{h(welcome_text)}"
        return text, contact_url

    async def _show_age_gate(self, message: Message) -> None:
        warning = await self.catalog.get_setting(
            "age_warning",
            "Каталог доступний лише користувачам віком від 18 років.",
        )
        await message.answer(h(warning), reply_markup=user_kb.age_confirmation())

    async def _has_access(self, user_id: int) -> bool:
        if user_id in self._session_age_confirmations:
            return True
        try:
            confirmed = await self.catalog.is_age_confirmed(user_id)
        except Exception:
            logging.exception("Не вдалося перевірити підтвердження віку для user_id=%s", user_id)
            return False
        if confirmed:
            self._session_age_confirmations.add(user_id)
        return confirmed

    async def start(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        if not await self._has_access(message.from_user.id):
            await self._show_age_gate(message)
            return
        text, contact_url = await self._home_text()
        await message.answer(text, reply_markup=user_kb.main_menu(contact_url))

    async def catalog_command(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        if not await self._has_access(message.from_user.id):
            await self._show_age_gate(message)
            return
        categories = await self.catalog.list_categories()
        await message.answer(
            "<b>🛍 Каталог</b>\n\nОберіть категорію:",
            reply_markup=user_kb.categories_menu(categories),
        )

    async def noop(self, callback: CallbackQuery) -> None:
        await callback.answer()

    async def age_yes(self, callback: CallbackQuery, state: FSMContext) -> None:
        # Відповідаємо Telegram одразу, щоб на кнопці не крутився індикатор.
        await callback.answer("Вік підтверджено")
        await state.clear()

        user_id = callback.from_user.id
        self._session_age_confirmations.add(user_id)

        try:
            await self.catalog.confirm_age(user_id)
        except Exception:
            # Навіть якщо Turso щойно прокидається, користувач одразу потрапить
            # у каталог. Після наступного натискання запис буде зроблено знову.
            logging.exception("Не вдалося зберегти підтвердження віку для user_id=%s", user_id)

        text, contact_url = await self._home_text()
        keyboard = user_kb.main_menu(contact_url)
        if callback.message:
            try:
                await replace_with_text(callback.message, text, keyboard)
            except Exception:
                logging.exception("Не вдалося замінити повідомлення після підтвердження віку")
                await callback.message.answer(text, reply_markup=keyboard)

    async def age_no(self, callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        if callback.message:
            await replace_with_text(
                callback.message,
                "Доступ до каталогу закрито. Повертайтеся після досягнення повноліття.",
            )

    async def home(self, callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if not await self._has_access(callback.from_user.id):
            if callback.message:
                warning = await self.catalog.get_setting("age_warning")
                await replace_with_text(
                    callback.message,
                    h(warning),
                    user_kb.age_confirmation(),
                )
            await callback.answer()
            return

        text, contact_url = await self._home_text()
        if callback.message:
            await replace_with_text(
                callback.message,
                text,
                user_kb.main_menu(contact_url),
            )
        await callback.answer()

    async def catalog_callback(self, callback: CallbackQuery) -> None:
        if not await self._has_access(callback.from_user.id):
            await callback.answer("Спочатку підтвердьте свій вік", show_alert=True)
            return
        categories = await self.catalog.list_categories()
        if callback.message:
            await replace_with_text(
                callback.message,
                "<b>🛍 Каталог</b>\n\nОберіть категорію:",
                user_kb.categories_menu(categories),
            )
        await callback.answer()

    async def info(self, callback: CallbackQuery) -> None:
        address = await self.catalog.get_setting("address_schedule")
        if callback.message:
            await replace_with_text(
                callback.message,
                f"<b>📍 Адреса та графік</b>\n\n{h(address)}",
                user_kb.back_home(),
            )
        await callback.answer()

    async def category(self, callback: CallbackQuery) -> None:
        if not callback.data or not callback.message:
            return
        _, _, category_id_raw, page_raw = callback.data.split(":", maxsplit=3)
        category_id = int(category_id_raw)
        page = max(0, int(page_raw))
        category = await self.catalog.get_category(category_id)
        if category is None or not category.active:
            await callback.answer("Категорія недоступна", show_alert=True)
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
        currency = await self.catalog.get_setting("currency", "грн")
        empty_text = "\n\nУ цій категорії поки немає доступних товарів." if not products else ""
        text = (
            f"<b>{h(category.emoji)} {h(category.name)}</b>"
            f"{empty_text}\n\nОберіть товар:"
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
            ),
        )
        await callback.answer()

    async def product(self, callback: CallbackQuery, bot: Bot) -> None:
        if not callback.data or not callback.message:
            return
        _, _, product_id_raw, page_raw = callback.data.split(":", maxsplit=3)
        product_id = int(product_id_raw)
        return_page = max(0, int(page_raw))
        product = await self.catalog.get_product(product_id)
        if product is None:
            await callback.answer("Товар не знайдено", show_alert=True)
            return

        currency = await self.catalog.get_setting("currency", "грн")
        await replace_with_photo_or_text(
            bot,
            callback.message,
            text=product_card_text(product, currency),
            photo_file_id=product.photo_file_id,
            reply_markup=user_kb.product_menu(product, return_page),
        )
        await callback.answer()

    async def search_start(self, callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(UserSearchStates.query)
        if callback.message:
            await replace_with_text(
                callback.message,
                "<b>🔎 Пошук товару</b>\n\nВведіть назву моделі або бренд одним повідомленням.",
                user_kb.back_home(),
            )
        await callback.answer()

    async def search_message(self, message: Message, state: FSMContext) -> None:
        query = (message.text or "").strip()
        if len(query) < 2:
            await message.answer("Введіть щонайменше 2 символи.")
            return

        products = await self.catalog.search_products(query)
        currency = await self.catalog.get_setting("currency", "грн")
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

    async def inquiry(self, callback: CallbackQuery, bot: Bot) -> None:
        if not callback.data:
            return
        product_id = int(callback.data.rsplit(":", maxsplit=1)[1])
        product = await self.catalog.get_product(product_id)
        if product is None or not product.in_stock:
            await callback.answer("Товар зараз недоступний", show_alert=True)
            return

        inquiry_id, created = await self.inquiries.create(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
            product_id=product_id,
        )
        inquiry = await self.inquiries.get(inquiry_id)
        if created and inquiry is not None:
            currency = await self.catalog.get_setting("currency", "грн")
            for admin_id in self.admin_ids:
                try:
                    await bot.send_message(
                        admin_id,
                        inquiry_text(inquiry, currency),
                        reply_markup=admin_kb.inquiry_actions(inquiry.id, inquiry.user_id),
                    )
                except (TelegramForbiddenError, TelegramBadRequest):
                    continue

        message = (
            "Запит надіслано продавцю. Вам напишуть у Telegram."
            if created
            else "Ваш запит щодо цього товару вже надіслано продавцю."
        )
        await callback.answer(message, show_alert=True)
