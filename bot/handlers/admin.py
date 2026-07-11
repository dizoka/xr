from __future__ import annotations

import math

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.core.constants import PRODUCTS_PER_PAGE
from bot.keyboards import admin as admin_kb
from bot.repositories.catalog_repository import CatalogRepository
from bot.repositories.inquiry_repository import InquiryRepository
from bot.states.admin import (
    AddCategoryStates,
    AddProductStates,
    EditCategoryStates,
    EditProductStates,
    EditSettingStates,
)
from bot.utils.admin_middleware import AdminOnlyMiddleware
from bot.utils.callbacks import CallbackErrorMiddleware, answer_callback_safely
from bot.utils.messages import replace_with_photo_or_text, replace_with_text
from bot.utils.text import admin_product_text, h, inquiry_text


class AdminHandlers:
    """Реєструє та обробляє інтерфейс керування каталогом."""

    def __init__(
        self,
        catalog: CatalogRepository,
        inquiries: InquiryRepository,
        admin_ids: frozenset[int],
    ) -> None:
        self.catalog = catalog
        self.inquiries = inquiries
        self.router = Router(name="admin")
        middleware = AdminOnlyMiddleware(admin_ids)
        self.router.message.middleware(middleware)
        self.router.callback_query.middleware(middleware)
        self.router.callback_query.middleware(
            CallbackErrorMiddleware(fallback_text="Не вдалося виконати дію в адмін-панелі.")
        )
        self._register()

    def _register(self) -> None:
        self.router.message.register(self.admin_command, Command("admin"))

        self.router.message.register(self.add_category_emoji, AddCategoryStates.emoji, F.text)
        self.router.message.register(self.add_category_name, AddCategoryStates.name, F.text)
        self.router.message.register(self.edit_category_value, EditCategoryStates.value, F.text)

        self.router.message.register(self.add_product_name, AddProductStates.name, F.text)
        self.router.message.register(self.add_product_brand, AddProductStates.brand, F.text)
        self.router.message.register(self.add_product_price, AddProductStates.price, F.text)
        self.router.message.register(
            self.add_product_description,
            AddProductStates.description,
            F.text,
        )
        self.router.message.register(self.add_product_photo, AddProductStates.photo, F.photo)
        self.router.message.register(self.add_product_photo_invalid, AddProductStates.photo)

        self.router.message.register(self.edit_product_photo, EditProductStates.value, F.photo)
        self.router.message.register(self.edit_product_value, EditProductStates.value, F.text)
        self.router.message.register(self.edit_setting_value, EditSettingStates.value, F.text)

        self.router.callback_query.register(self.cancel, F.data == "a:cancel")
        self.router.callback_query.register(self.home, F.data == "a:home")
        self.router.callback_query.register(self.categories, F.data == "a:cats")
        self.router.callback_query.register(self.category_add_start, F.data == "a:catadd")
        self.router.callback_query.register(self.category_detail, F.data.startswith("a:cat:"))
        self.router.callback_query.register(self.category_name_start, F.data.startswith("a:catname:"))
        self.router.callback_query.register(self.category_emoji_start, F.data.startswith("a:catemoji:"))
        self.router.callback_query.register(self.category_toggle, F.data.startswith("a:cattoggle:"))
        self.router.callback_query.register(self.category_delete, F.data.startswith("a:catdel:"))
        self.router.callback_query.register(self.category_delete_confirm, F.data.startswith("a:catdelok:"))

        self.router.callback_query.register(self.products, F.data == "a:products")
        self.router.callback_query.register(self.products_list, F.data.startswith("a:plist:"))
        self.router.callback_query.register(self.product_add_start, F.data.startswith("a:padd:"))
        self.router.callback_query.register(
            self.product_photo_skip,
            AddProductStates.photo,
            F.data == "a:photoskip",
        )
        self.router.callback_query.register(self.product_detail, F.data.startswith("a:p:"))
        self.router.callback_query.register(self.product_edit_start, F.data.startswith("a:pe:"))
        self.router.callback_query.register(self.product_photo_delete, F.data.startswith("a:photodel:"))
        self.router.callback_query.register(self.product_toggle, F.data.startswith("a:ptoggle:"))
        self.router.callback_query.register(self.product_delete, F.data.startswith("a:pdel:"))
        self.router.callback_query.register(self.product_delete_confirm, F.data.startswith("a:pdelok:"))

        self.router.callback_query.register(self.settings, F.data == "a:settings")
        self.router.callback_query.register(self.setting_edit_start, F.data.startswith("a:set:"))
        self.router.callback_query.register(self.requests, F.data == "a:reqs")
        self.router.callback_query.register(self.request_detail, F.data.startswith("a:req:"))
        self.router.callback_query.register(self.request_done, F.data.startswith("a:reqdone:"))
        self.router.callback_query.register(self.stats, F.data == "a:stats")
        self.router.callback_query.register(self.unknown_admin_button, F.data.startswith("a:"))

    async def unknown_admin_button(self, callback: CallbackQuery, state: FSMContext) -> None:
        await answer_callback_safely(
            callback,
            "Кнопку оновлено. Відкриваю адмін-панель.",
        )
        await state.clear()
        if callback.message:
            await replace_with_text(
                callback.message,
                await self._admin_text(),
                admin_kb.main_menu(),
            )

    async def _admin_text(self) -> str:
        stats = await self.catalog.stats()
        return (
            "<b>⚙️ Адмін-панель CrystalStore</b>\n\n"
            f"Категорій: <b>{stats.categories}</b>\n"
            f"Товарів: <b>{stats.products}</b>\n"
            f"У наявності: <b>{stats.in_stock}</b>\n"
            f"Нових запитів: <b>{stats.open_inquiries}</b>"
        )

    async def admin_command(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(await self._admin_text(), reply_markup=admin_kb.main_menu())

    async def home(self, callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if callback.message:
            await replace_with_text(
                callback.message,
                await self._admin_text(),
                admin_kb.main_menu(),
            )
        await answer_callback_safely(callback)

    async def cancel(self, callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if callback.message:
            await replace_with_text(
                callback.message,
                await self._admin_text(),
                admin_kb.main_menu(),
            )
        await answer_callback_safely(callback, "Дію скасовано")

    # Categories
    async def categories(self, callback: CallbackQuery) -> None:
        categories = await self.catalog.list_categories(include_inactive=True)
        if callback.message:
            await replace_with_text(
                callback.message,
                "<b>📂 Категорії</b>\n\n✅ — видима покупцям\n⛔ — прихована",
                admin_kb.categories_list(categories),
            )
        await answer_callback_safely(callback)

    async def category_add_start(self, callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(AddCategoryStates.emoji)
        if callback.message:
            await replace_with_text(
                callback.message,
                "Надішліть емодзі нової категорії. Наприклад: <b>💨</b>",
                admin_kb.cancel(),
            )
        await answer_callback_safely(callback)

    async def add_category_emoji(self, message: Message, state: FSMContext) -> None:
        emoji = (message.text or "").strip()
        if not emoji or len(emoji) > 12:
            await message.answer("Надішліть один короткий емодзі.")
            return
        await state.update_data(emoji=emoji)
        await state.set_state(AddCategoryStates.name)
        await message.answer("Тепер надішліть назву категорії.", reply_markup=admin_kb.cancel())

    async def add_category_name(self, message: Message, state: FSMContext) -> None:
        name = (message.text or "").strip()
        if len(name) < 2 or len(name) > 50:
            await message.answer("Назва має містити від 2 до 50 символів.")
            return
        data = await state.get_data()
        await self.catalog.add_category(name=name, emoji=str(data["emoji"]))
        await state.clear()
        categories = await self.catalog.list_categories(include_inactive=True)
        await message.answer(
            "✅ Категорію додано.",
            reply_markup=admin_kb.categories_list(categories),
        )

    async def category_detail(self, callback: CallbackQuery) -> None:
        if not callback.data or not callback.message:
            return
        category_id = int(callback.data.rsplit(":", 1)[1])
        category = await self.catalog.get_category(category_id)
        if category is None:
            await answer_callback_safely(callback, "Категорію не знайдено", show_alert=True)
            return
        product_count = await self.catalog.count_products(category_id)
        status = "✅ Відображається" if category.active else "⛔ Прихована"
        text = (
            f"<b>{h(category.emoji)} {h(category.name)}</b>\n\n"
            f"Статус: {status}\n"
            f"Товарів: <b>{product_count}</b>\n\n"
            "Під час видалення категорії також буде видалено всі товари в ній."
        )
        await replace_with_text(callback.message, text, admin_kb.category_actions(category))
        await answer_callback_safely(callback)

    async def category_name_start(self, callback: CallbackQuery, state: FSMContext) -> None:
        category_id = int((callback.data or "").rsplit(":", 1)[1])
        await state.set_state(EditCategoryStates.value)
        await state.update_data(category_id=category_id, field="name")
        if callback.message:
            await replace_with_text(
                callback.message,
                "Надішліть нову назву категорії.",
                admin_kb.cancel(),
            )
        await answer_callback_safely(callback)

    async def category_emoji_start(self, callback: CallbackQuery, state: FSMContext) -> None:
        category_id = int((callback.data or "").rsplit(":", 1)[1])
        await state.set_state(EditCategoryStates.value)
        await state.update_data(category_id=category_id, field="emoji")
        if callback.message:
            await replace_with_text(
                callback.message,
                "Надішліть новий емодзі категорії.",
                admin_kb.cancel(),
            )
        await answer_callback_safely(callback)

    async def edit_category_value(self, message: Message, state: FSMContext) -> None:
        value = (message.text or "").strip()
        data = await state.get_data()
        category_id = int(data["category_id"])
        field = str(data["field"])
        if field == "name":
            if len(value) < 2 or len(value) > 50:
                await message.answer("Назва має містити від 2 до 50 символів.")
                return
            await self.catalog.update_category_name(category_id, value)
        else:
            if not value or len(value) > 12:
                await message.answer("Надішліть один короткий емодзі.")
                return
            await self.catalog.update_category_emoji(category_id, value)
        await state.clear()
        category = await self.catalog.get_category(category_id)
        if category:
            await message.answer("✅ Категорію оновлено.", reply_markup=admin_kb.category_actions(category))

    async def category_toggle(self, callback: CallbackQuery) -> None:
        category_id = int((callback.data or "").rsplit(":", 1)[1])
        await self.catalog.toggle_category(category_id)
        category = await self.catalog.get_category(category_id)
        if category and callback.message:
            count = await self.catalog.count_products(category_id)
            status = "✅ Відображається" if category.active else "⛔ Прихована"
            await replace_with_text(
                callback.message,
                f"<b>{h(category.emoji)} {h(category.name)}</b>\n\nСтатус: {status}\nТоварів: <b>{count}</b>",
                admin_kb.category_actions(category),
            )
        await answer_callback_safely(callback, "Статус змінено")

    async def category_delete(self, callback: CallbackQuery) -> None:
        category_id = int((callback.data or "").rsplit(":", 1)[1])
        category = await self.catalog.get_category(category_id)
        if category and callback.message:
            await replace_with_text(
                callback.message,
                f"Видалити категорію <b>{h(category.name)}</b> та всі товари в ній?",
                admin_kb.confirm_category_delete(category_id),
            )
        await answer_callback_safely(callback)

    async def category_delete_confirm(self, callback: CallbackQuery) -> None:
        category_id = int((callback.data or "").rsplit(":", 1)[1])
        await self.catalog.delete_category(category_id)
        categories = await self.catalog.list_categories(include_inactive=True)
        if callback.message:
            await replace_with_text(
                callback.message,
                "✅ Категорію видалено.",
                admin_kb.categories_list(categories),
            )
        await answer_callback_safely(callback)

    # Products
    async def products(self, callback: CallbackQuery) -> None:
        categories = await self.catalog.list_categories(include_inactive=True)
        if callback.message:
            await replace_with_text(
                callback.message,
                "<b>📦 Керування товарами</b>\n\nОберіть категорію:",
                admin_kb.product_categories(categories),
            )
        await answer_callback_safely(callback)

    async def products_list(self, callback: CallbackQuery) -> None:
        if not callback.data or not callback.message:
            return
        _, _, category_id_raw, page_raw = callback.data.split(":", maxsplit=3)
        category_id = int(category_id_raw)
        page = max(0, int(page_raw))
        category = await self.catalog.get_category(category_id)
        if category is None:
            await answer_callback_safely(callback, "Категорію не знайдено", show_alert=True)
            return
        total = await self.catalog.count_products(category_id)
        total_pages = max(1, math.ceil(total / PRODUCTS_PER_PAGE))
        page = min(page, total_pages - 1)
        products = await self.catalog.list_products(
            category_id,
            limit=PRODUCTS_PER_PAGE,
            offset=page * PRODUCTS_PER_PAGE,
        )
        currency = await self.catalog.get_setting("currency", "грн")
        text = f"<b>{h(category.emoji)} {h(category.name)}</b>\n\nТоварів: {total}"
        if not products:
            text += "\n\nТоварів поки немає — додайте перший."
        await replace_with_text(
            callback.message,
            text,
            admin_kb.admin_products_list(
                products,
                category_id=category_id,
                page=page,
                total_pages=total_pages,
                currency=currency,
            ),
        )
        await answer_callback_safely(callback)

    async def product_add_start(self, callback: CallbackQuery, state: FSMContext) -> None:
        category_id = int((callback.data or "").rsplit(":", 1)[1])
        category = await self.catalog.get_category(category_id)
        if category is None:
            await answer_callback_safely(callback, "Категорію не знайдено", show_alert=True)
            return
        await state.set_state(AddProductStates.name)
        await state.update_data(category_id=category_id)
        if callback.message:
            await replace_with_text(
                callback.message,
                f"Додавання товару до <b>{h(category.name)}</b>.\n\nНадішліть назву моделі.",
                admin_kb.cancel(),
            )
        await answer_callback_safely(callback)

    async def add_product_name(self, message: Message, state: FSMContext) -> None:
        value = (message.text or "").strip()
        if len(value) < 2 or len(value) > 100:
            await message.answer("Назва має містити від 2 до 100 символів.")
            return
        await state.update_data(name=value)
        await state.set_state(AddProductStates.brand)
        await message.answer("Надішліть бренд. Щоб залишити поле порожнім, надішліть <b>-</b>.", reply_markup=admin_kb.cancel())

    async def add_product_brand(self, message: Message, state: FSMContext) -> None:
        value = (message.text or "").strip()
        if len(value) > 80:
            await message.answer("Назва бренду надто довга.")
            return
        await state.update_data(brand="" if value == "-" else value)
        await state.set_state(AddProductStates.price)
        await message.answer("Надішліть ціну числом або текстом, наприклад: <b>950</b>.", reply_markup=admin_kb.cancel())

    async def add_product_price(self, message: Message, state: FSMContext) -> None:
        value = (message.text or "").strip()
        if not value or len(value) > 30:
            await message.answer("Введіть коректну ціну довжиною до 30 символів.")
            return
        await state.update_data(price=value)
        await state.set_state(AddProductStates.description)
        await message.answer("Надішліть опис товару. Щоб залишити поле порожнім, надішліть <b>-</b>.", reply_markup=admin_kb.cancel())

    async def add_product_description(self, message: Message, state: FSMContext) -> None:
        value = (message.text or "").strip()
        if len(value) > 900:
            await message.answer("Опис надто довгий. Максимум 900 символів.")
            return
        await state.update_data(description="" if value == "-" else value)
        await state.set_state(AddProductStates.photo)
        await message.answer(
            "Надішліть фотографію товару або натисніть «Без фото».",
            reply_markup=admin_kb.photo_step(),
        )

    async def _finish_add_product(self, message: Message, state: FSMContext, photo_file_id: str | None) -> None:
        data = await state.get_data()
        product_id = await self.catalog.add_product(
            category_id=int(data["category_id"]),
            name=str(data["name"]),
            brand=str(data["brand"]),
            price=str(data["price"]),
            description=str(data["description"]),
            photo_file_id=photo_file_id,
        )
        await state.clear()
        product = await self.catalog.get_product(product_id)
        currency = await self.catalog.get_setting("currency", "грн")
        if product:
            await message.answer(
                "✅ Товар додано.\n\n" + admin_product_text(product, currency),
                reply_markup=admin_kb.product_actions(product, 0),
            )

    async def add_product_photo(self, message: Message, state: FSMContext) -> None:
        await self._finish_add_product(message, state, message.photo[-1].file_id)

    async def add_product_photo_invalid(self, message: Message) -> None:
        await message.answer("Потрібно надіслати саме фотографію або натиснути «Без фото».", reply_markup=admin_kb.photo_step())

    async def product_photo_skip(self, callback: CallbackQuery, state: FSMContext) -> None:
        if callback.message:
            await self._finish_add_product(callback.message, state, None)
        await answer_callback_safely(callback)

    async def product_detail(self, callback: CallbackQuery, bot: Bot) -> None:
        if not callback.data or not callback.message:
            return
        _, _, product_id_raw, page_raw = callback.data.split(":", maxsplit=3)
        product = await self.catalog.get_product(int(product_id_raw))
        if product is None:
            await answer_callback_safely(callback, "Товар не знайдено", show_alert=True)
            return
        page = max(0, int(page_raw))
        currency = await self.catalog.get_setting("currency", "грн")
        await replace_with_photo_or_text(
            bot,
            callback.message,
            text=admin_product_text(product, currency),
            photo_file_id=product.photo_file_id,
            reply_markup=admin_kb.product_actions(product, page),
        )
        await answer_callback_safely(callback)

    async def product_edit_start(self, callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.data:
            return
        _, _, field, product_id_raw = callback.data.split(":", maxsplit=3)
        product_id = int(product_id_raw)
        product = await self.catalog.get_product(product_id)
        if product is None:
            await answer_callback_safely(callback, "Товар не знайдено", show_alert=True)
            return
        prompts = {
            "name": "Надішліть нову назву товару.",
            "brand": "Надішліть новий бренд. Щоб очистити поле, надішліть -.",
            "price": "Надішліть нову ціну.",
            "description": "Надішліть новий опис. Щоб очистити поле, надішліть -.",
            "photo_file_id": "Надішліть нову фотографію товару.",
        }
        await state.set_state(EditProductStates.value)
        await state.update_data(product_id=product_id, field=field)
        keyboard = admin_kb.edit_photo(product_id) if field == "photo_file_id" else admin_kb.cancel()
        if callback.message:
            await replace_with_text(callback.message, prompts[field], keyboard)
        await answer_callback_safely(callback)

    async def edit_product_photo(self, message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        if data.get("field") != "photo_file_id":
            await message.answer("У цьому полі потрібно надіслати текст.")
            return
        product_id = int(data["product_id"])
        await self.catalog.update_product_field(product_id, "photo_file_id", message.photo[-1].file_id)
        await state.clear()
        product = await self.catalog.get_product(product_id)
        currency = await self.catalog.get_setting("currency", "грн")
        if product:
            await message.answer("✅ Фото оновлено.\n\n" + admin_product_text(product, currency), reply_markup=admin_kb.product_actions(product, 0))

    async def edit_product_value(self, message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        field = str(data.get("field", ""))
        product_id = int(data.get("product_id", 0))
        if field == "photo_file_id":
            await message.answer("Надішліть фотографію, а не текст.", reply_markup=admin_kb.edit_photo(product_id))
            return
        value = (message.text or "").strip()
        if field == "name" and not (2 <= len(value) <= 100):
            await message.answer("Назва має містити від 2 до 100 символів.")
            return
        if field == "brand" and len(value) > 80:
            await message.answer("Назва бренду надто довга.")
            return
        if field == "price" and (not value or len(value) > 30):
            await message.answer("Введіть коректну ціну.")
            return
        if field == "description" and len(value) > 900:
            await message.answer("Опис надто довгий. Максимум 900 символів.")
            return
        if field in {"brand", "description"} and value == "-":
            value = ""
        await self.catalog.update_product_field(product_id, field, value)
        await state.clear()
        product = await self.catalog.get_product(product_id)
        currency = await self.catalog.get_setting("currency", "грн")
        if product:
            await message.answer("✅ Товар оновлено.\n\n" + admin_product_text(product, currency), reply_markup=admin_kb.product_actions(product, 0))

    async def product_photo_delete(self, callback: CallbackQuery, state: FSMContext) -> None:
        product_id = int((callback.data or "").rsplit(":", 1)[1])
        await self.catalog.update_product_field(product_id, "photo_file_id", None)
        await state.clear()
        product = await self.catalog.get_product(product_id)
        currency = await self.catalog.get_setting("currency", "грн")
        if product and callback.message:
            await replace_with_text(
                callback.message,
                "✅ Фото видалено.\n\n" + admin_product_text(product, currency),
                admin_kb.product_actions(product, 0),
            )
        await answer_callback_safely(callback)

    async def product_toggle(self, callback: CallbackQuery, bot: Bot) -> None:
        if not callback.data or not callback.message:
            return
        _, _, product_id_raw, page_raw = callback.data.split(":", maxsplit=3)
        product_id = int(product_id_raw)
        await self.catalog.toggle_product_stock(product_id)
        product = await self.catalog.get_product(product_id)
        currency = await self.catalog.get_setting("currency", "грн")
        if product:
            await replace_with_photo_or_text(
                bot,
                callback.message,
                text=admin_product_text(product, currency),
                photo_file_id=product.photo_file_id,
                reply_markup=admin_kb.product_actions(product, int(page_raw)),
            )
        await answer_callback_safely(callback, "Статус товару змінено")

    async def product_delete(self, callback: CallbackQuery) -> None:
        if not callback.data or not callback.message:
            return
        _, _, product_id_raw, page_raw = callback.data.split(":", maxsplit=3)
        product = await self.catalog.get_product(int(product_id_raw))
        if product:
            await replace_with_text(
                callback.message,
                f"Видалити товар <b>{h(product.name)}</b>?",
                admin_kb.confirm_product_delete(product.id, int(page_raw)),
            )
        await answer_callback_safely(callback)

    async def product_delete_confirm(self, callback: CallbackQuery) -> None:
        if not callback.data or not callback.message:
            return
        _, _, product_id_raw, page_raw = callback.data.split(":", maxsplit=3)
        product = await self.catalog.get_product(int(product_id_raw))
        if product is None:
            await answer_callback_safely(callback, "Товар уже видалено", show_alert=True)
            return
        category_id = product.category_id
        await self.catalog.delete_product(product.id)
        total = await self.catalog.count_products(category_id)
        total_pages = max(1, math.ceil(total / PRODUCTS_PER_PAGE))
        page = min(int(page_raw), total_pages - 1)
        products = await self.catalog.list_products(
            category_id,
            limit=PRODUCTS_PER_PAGE,
            offset=page * PRODUCTS_PER_PAGE,
        )
        currency = await self.catalog.get_setting("currency", "грн")
        category = await self.catalog.get_category(category_id)
        title = category.name if category else "Категорія"
        await replace_with_text(
            callback.message,
            f"✅ Товар видалено.\n\n<b>{h(title)}</b>",
            admin_kb.admin_products_list(
                products,
                category_id=category_id,
                page=page,
                total_pages=total_pages,
                currency=currency,
            ),
        )
        await answer_callback_safely(callback)

    # Settings
    async def settings(self, callback: CallbackQuery) -> None:
        values = await self.catalog.get_all_settings()
        text = (
            "<b>⚙️ Налаштування магазину</b>\n\n"
            f"Назва: {h(values.get('store_name', ''))}\n"
            f"Валюта: {h(values.get('currency', ''))}\n"
            f"Посилання продавця: {h(values.get('contact_url', ''))}\n"
            f"Посилання на акції: {h(values.get('promotions_url', 'Не задано')) or 'Не задано'}\n\n"
            "Оберіть параметр для зміни."
        )
        if callback.message:
            await replace_with_text(callback.message, text, admin_kb.settings_menu())
        await answer_callback_safely(callback)

    async def setting_edit_start(self, callback: CallbackQuery, state: FSMContext) -> None:
        key = (callback.data or "").split(":", maxsplit=2)[2]
        allowed = {
            "store_name",
            "welcome_text",
            "address_schedule",
            "contact_url",
            "promotions_url",
            "currency",
            "age_warning",
        }
        if key not in allowed:
            await answer_callback_safely(callback, "Невідоме налаштування", show_alert=True)
            return
        current = await self.catalog.get_setting(key)
        await state.set_state(EditSettingStates.value)
        await state.update_data(key=key)
        if callback.message:
            await replace_with_text(
                callback.message,
                f"Поточне значення:\n<code>{h(current)}</code>\n\nНадішліть нове значення.",
                admin_kb.cancel(),
            )
        await answer_callback_safely(callback)

    async def edit_setting_value(self, message: Message, state: FSMContext) -> None:
        value = (message.text or "").strip()
        data = await state.get_data()
        key = str(data["key"])
        if not value:
            await message.answer("Значення не може бути порожнім.")
            return
        if key in {"contact_url", "promotions_url"} and not value.startswith(("https://", "http://", "tg://")):
            await message.answer("Посилання має починатися з https://, http:// або tg://")
            return
        await self.catalog.set_setting(key, value)
        await state.clear()
        await message.answer("✅ Налаштування збережено.", reply_markup=admin_kb.settings_menu())

    # Inquiries and statistics
    async def requests(self, callback: CallbackQuery) -> None:
        inquiries = await self.inquiries.list_open()
        text = "<b>📝 Нові запити</b>\n\n"
        text += f"Відкритих запитів: <b>{len(inquiries)}</b>"
        if not inquiries:
            text += "\n\nНових запитів поки немає."
        if callback.message:
            await replace_with_text(callback.message, text, admin_kb.inquiries_list(inquiries))
        await answer_callback_safely(callback)

    async def request_detail(self, callback: CallbackQuery) -> None:
        inquiry_id = int((callback.data or "").rsplit(":", 1)[1])
        inquiry = await self.inquiries.get(inquiry_id)
        if inquiry is None:
            await answer_callback_safely(callback, "Запит не знайдено", show_alert=True)
            return
        currency = await self.catalog.get_setting("currency", "грн")
        if callback.message:
            await replace_with_text(
                callback.message,
                inquiry_text(inquiry, currency),
                admin_kb.inquiry_actions(inquiry.id, inquiry.user_id),
            )
        await answer_callback_safely(callback)

    async def request_done(self, callback: CallbackQuery) -> None:
        inquiry_id = int((callback.data or "").rsplit(":", 1)[1])
        await self.inquiries.mark_done(inquiry_id)
        inquiries = await self.inquiries.list_open()
        if callback.message:
            await replace_with_text(
                callback.message,
                "✅ Запит позначено як опрацьований.",
                admin_kb.inquiries_list(inquiries),
            )
        await answer_callback_safely(callback)

    async def stats(self, callback: CallbackQuery) -> None:
        stats = await self.catalog.stats()
        text = (
            "<b>📊 Статистика каталогу</b>\n\n"
            f"Категорій: <b>{stats.categories}</b>\n"
            f"Усього товарів: <b>{stats.products}</b>\n"
            f"Доступно покупцям: <b>{stats.in_stock}</b>\n"
            f"Нових запитів: <b>{stats.open_inquiries}</b>"
        )
        if callback.message:
            await replace_with_text(callback.message, text, admin_kb.main_menu())
        await answer_callback_safely(callback)
