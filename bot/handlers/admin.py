from __future__ import annotations

import math

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, BotCommandScopeChat, CallbackQuery, Message

from bot.core.constants import PRODUCTS_PER_PAGE
from bot.keyboards import admin as admin_kb
from bot.middlewares.rate_limit import RateLimitMiddleware
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
from bot.utils.product_types import VALID_VARIANT_TYPES, infer_variant_type
from bot.utils.text import admin_product_text, h, inquiry_text
from bot.utils.validators import normalize_price


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
        self.owner_ids = admin_ids
        middleware = AdminOnlyMiddleware(admin_ids, catalog)
        self.router.message.middleware(middleware)
        self.router.callback_query.middleware(middleware)
        self.router.callback_query.middleware(
            CallbackErrorMiddleware(
                fallback_text="Не вдалося виконати дію в адмін-панелі."
            )
        )
        self.router.message.middleware(RateLimitMiddleware(limit=12, period=5))
        self.router.callback_query.middleware(RateLimitMiddleware(limit=16, period=5))
        self._register()

    def _register(self) -> None:
        self.router.message.register(self.admin_command, Command("admin"))
        self.router.message.register(self.add_staff_command, Command("addadmin"))
        self.router.message.register(self.remove_staff_command, Command("deladmin"))
        self.router.message.register(self.list_staff_command, Command("admins"))

        self.router.message.register(
            self.add_category_emoji, AddCategoryStates.emoji, F.text
        )
        self.router.message.register(
            self.add_category_name, AddCategoryStates.name, F.text
        )
        self.router.message.register(
            self.edit_category_value, EditCategoryStates.value, F.text
        )

        self.router.message.register(
            self.add_product_name, AddProductStates.name, F.text
        )
        self.router.message.register(
            self.add_product_brand, AddProductStates.brand, F.text
        )
        self.router.message.register(
            self.add_product_price, AddProductStates.price, F.text
        )
        self.router.message.register(
            self.add_product_description,
            AddProductStates.description,
            F.text,
        )
        self.router.message.register(
            self.add_product_photo, AddProductStates.photo, F.photo
        )
        self.router.message.register(
            self.add_product_photo_invalid, AddProductStates.photo
        )

        self.router.message.register(
            self.edit_product_photo, EditProductStates.value, F.photo
        )
        self.router.message.register(
            self.edit_product_value, EditProductStates.value, F.text
        )
        self.router.message.register(
            self.edit_setting_value, EditSettingStates.value, F.text
        )

        self.router.callback_query.register(self.cancel, F.data == "a:cancel")
        self.router.callback_query.register(self.home, F.data == "a:home")
        self.router.callback_query.register(self.categories, F.data == "a:cats")
        self.router.callback_query.register(
            self.category_add_start, F.data.startswith("a:catadd")
        )
        self.router.callback_query.register(
            self.category_detail, F.data.startswith("a:cat:")
        )
        self.router.callback_query.register(
            self.subcategories, F.data.startswith("a:subcats:")
        )
        self.router.callback_query.register(
            self.category_name_start, F.data.startswith("a:catname:")
        )
        self.router.callback_query.register(
            self.category_emoji_start, F.data.startswith("a:catemoji:")
        )
        self.router.callback_query.register(
            self.category_toggle, F.data.startswith("a:cattoggle:")
        )
        self.router.callback_query.register(
            self.category_delete, F.data.startswith("a:catdel:")
        )
        self.router.callback_query.register(
            self.category_delete_confirm, F.data.startswith("a:catdelok:")
        )

        self.router.callback_query.register(self.products, F.data == "a:products")
        self.router.callback_query.register(
            self.products_list, F.data.startswith("a:plist:")
        )
        self.router.callback_query.register(
            self.product_add_start, F.data.startswith("a:padd:")
        )
        self.router.callback_query.register(
            self.add_product_variant_type,
            AddProductStates.variant_type,
            F.data.startswith("a:vtypeadd:"),
        )
        self.router.callback_query.register(
            self.product_photo_skip,
            AddProductStates.photo,
            F.data == "a:photoskip",
        )
        self.router.callback_query.register(
            self.product_detail, F.data.startswith("a:p:")
        )
        self.router.callback_query.register(
            self.product_variant_type_edit_start,
            F.data.startswith("a:pe:variant_type:"),
        )
        self.router.callback_query.register(
            self.edit_product_variant_type,
            F.data.startswith("a:vtypeedit:"),
        )
        self.router.callback_query.register(
            self.product_edit_start,
            F.data.regexp(
                r"^a:pe:(name|brand|price|quantity|description|photo_file_id):"
            ),
        )
        self.router.callback_query.register(
            self.product_photo_delete, F.data.startswith("a:photodel:")
        )
        self.router.callback_query.register(
            self.product_toggle, F.data.startswith("a:ptoggle:")
        )
        self.router.callback_query.register(
            self.product_delete, F.data.startswith("a:pdel:")
        )
        self.router.callback_query.register(
            self.product_delete_confirm, F.data.startswith("a:pdelok:")
        )

        self.router.callback_query.register(self.settings, F.data == "a:settings")
        self.router.callback_query.register(
            self.setting_edit_start, F.data.startswith("a:set:")
        )
        self.router.callback_query.register(self.requests, F.data == "a:reqs")
        self.router.callback_query.register(
            self.request_detail, F.data.startswith("a:req:")
        )
        self.router.callback_query.register(
            self.request_done, F.data.startswith("a:reqdone:")
        )
        self.router.callback_query.register(self.stats, F.data == "a:stats")
        self.router.callback_query.register(
            self.unknown_admin_button, F.data.startswith("a:")
        )

    async def _resolve_staff_id(
        self, message: Message, command: CommandObject
    ) -> int | None:
        if message.reply_to_message and message.reply_to_message.from_user:
            return message.reply_to_message.from_user.id
        value = (command.args or "").strip()
        return int(value) if value.isdigit() else None

    async def add_staff_command(
        self,
        message: Message,
        command: CommandObject,
        state: FSMContext,
        bot: Bot,
        is_owner_admin: bool = False,
    ) -> None:
        await state.clear()
        if not is_owner_admin:
            await message.answer("Керувати адміністраторами може лише власник бота.")
            return
        user_id = await self._resolve_staff_id(message, command)
        if user_id is None or user_id in self.owner_ids:
            await message.answer(
                "Використання: <code>/addadmin TELEGRAM_ID</code> або відповідайте командою на повідомлення людини."
            )
            return
        await self.catalog.add_staff_admin(user_id)
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Відкрити головне меню"),
                BotCommand(command="catalog", description="Каталог товарів"),
                BotCommand(command="help", description="Допомога"),
                BotCommand(command="id", description="Показати мій Telegram ID"),
                BotCommand(command="admin", description="Адмін-панель"),
            ],
            scope=BotCommandScopeChat(chat_id=user_id),
        )
        await message.answer(
            f"✅ Користувачу <code>{user_id}</code> видано повну адмінку.\n"
            "Доступ: товари, категорії, заявки, налаштування та статистика.\n"
            "Керувати іншими адміністраторами може лише власник."
        )

    async def remove_staff_command(
        self,
        message: Message,
        command: CommandObject,
        state: FSMContext,
        bot: Bot,
        is_owner_admin: bool = False,
    ) -> None:
        await state.clear()
        if not is_owner_admin:
            await message.answer("Керувати адміністраторами може лише власник бота.")
            return
        user_id = await self._resolve_staff_id(message, command)
        if user_id is None:
            await message.answer("Використання: <code>/deladmin TELEGRAM_ID</code>")
            return
        await self.catalog.remove_staff_admin(user_id)
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=user_id))
        await message.answer(f"✅ Доступ працівника <code>{user_id}</code> забрано.")

    async def list_staff_command(
        self,
        message: Message,
        state: FSMContext,
        is_owner_admin: bool = False,
    ) -> None:
        await state.clear()
        if not is_owner_admin:
            await message.answer(
                "Переглядати список адміністраторів може лише власник бота."
            )
            return
        ids = await self.catalog.list_staff_admins()
        if not ids:
            await message.answer("Додаткових адміністраторів поки немає.")
            return
        lines = "\n".join(f"• <code>{user_id}</code>" for user_id in ids)
        await message.answer("<b>Додаткові адміністратори:</b>\n\n" + lines)

    async def unknown_admin_button(
        self, callback: CallbackQuery, state: FSMContext
    ) -> None:
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

    async def admin_command(
        self, message: Message, state: FSMContext, is_owner_admin: bool = False
    ) -> None:
        await state.clear()
        await message.answer(
            await self._admin_text(), reply_markup=admin_kb.main_menu()
        )

    async def home(
        self, callback: CallbackQuery, state: FSMContext, is_owner_admin: bool = False
    ) -> None:
        await state.clear()
        if callback.message:
            await replace_with_text(
                callback.message, await self._admin_text(), admin_kb.main_menu()
            )
        await answer_callback_safely(callback)

    async def cancel(
        self, callback: CallbackQuery, state: FSMContext, is_owner_admin: bool = False
    ) -> None:
        await state.clear()
        if callback.message:
            await replace_with_text(
                callback.message, await self._admin_text(), admin_kb.main_menu()
            )
        await answer_callback_safely(callback, "Дію скасовано")

    # Categories
    async def categories(self, callback: CallbackQuery) -> None:
        categories = await self.catalog.list_categories(include_inactive=True, parent_id=None)
        if callback.message:
            await replace_with_text(
                callback.message,
                "<b>📂 Категорії</b>\n\n✅ — видима покупцям\n⛔ — прихована",
                admin_kb.categories_list(categories),
            )
        await answer_callback_safely(callback)

    async def category_add_start(
        self, callback: CallbackQuery, state: FSMContext
    ) -> None:
        parts = (callback.data or "").split(":")
        parent_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        await state.update_data(parent_id=parent_id)
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
        await message.answer(
            "Тепер надішліть назву категорії.", reply_markup=admin_kb.cancel()
        )

    async def add_category_name(self, message: Message, state: FSMContext) -> None:
        name = (message.text or "").strip()
        if len(name) < 2 or len(name) > 50:
            await message.answer("Назва має містити від 2 до 50 символів.")
            return
        data = await state.get_data()
        parent_id = data.get("parent_id")
        await self.catalog.add_category(name=name, emoji=str(data["emoji"]), parent_id=(int(parent_id) if parent_id is not None else None))
        await state.clear()
        parent_id = data.get("parent_id")
        categories = await self.catalog.list_categories(include_inactive=True, parent_id=(int(parent_id) if parent_id is not None else None))
        await message.answer(
            "✅ Категорію додано.",
            reply_markup=admin_kb.categories_list(categories, int(parent_id) if parent_id is not None else None),
        )

    async def subcategories(self, callback: CallbackQuery) -> None:
        if not callback.data or not callback.message:
            return
        parent_id = int(callback.data.rsplit(":", 1)[1])
        parent = await self.catalog.get_category(parent_id)
        if parent is None:
            await answer_callback_safely(callback, "Категорію не знайдено", show_alert=True)
            return
        children = await self.catalog.list_categories(include_inactive=True, parent_id=parent_id)
        await replace_with_text(
            callback.message,
            f"<b>📂 {h(parent.name)} — підкатегорії</b>",
            admin_kb.categories_list(children, parent_id),
        )
        await answer_callback_safely(callback)

    async def category_detail(self, callback: CallbackQuery) -> None:
        if not callback.data or not callback.message:
            return
        category_id = int(callback.data.rsplit(":", 1)[1])
        category = await self.catalog.get_category(category_id)
        if category is None:
            await answer_callback_safely(
                callback, "Категорію не знайдено", show_alert=True
            )
            return
        product_count = await self.catalog.count_products(category_id)
        child_count = await self.catalog.count_child_categories(category_id)
        status = "✅ Відображається" if category.active else "⛔ Прихована"
        text = (
            f"<b>{h(category.emoji)} {h(category.name)}</b>\n\n"
            f"Статус: {status}\n"
            f"Підкатегорій: <b>{child_count}</b>\n"
            f"Товарів: <b>{product_count}</b>\n\n"
            "Під час видалення категорії також буде видалено всі товари в ній."
        )
        await replace_with_text(
            callback.message, text, admin_kb.category_actions(category)
        )
        await answer_callback_safely(callback)

    async def category_name_start(
        self, callback: CallbackQuery, state: FSMContext
    ) -> None:
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

    async def category_emoji_start(
        self, callback: CallbackQuery, state: FSMContext
    ) -> None:
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
            await message.answer(
                "✅ Категорію оновлено.",
                reply_markup=admin_kb.category_actions(category),
            )

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
    async def products(
        self, callback: CallbackQuery, is_owner_admin: bool = False
    ) -> None:
        categories = await self.catalog.list_categories(include_inactive=True, parent_id=None)
        if callback.message:
            await replace_with_text(
                callback.message,
                "<b>📦 Керування товарами</b>\n\nОберіть категорію:",
                admin_kb.product_categories(categories),
            )
        await answer_callback_safely(callback)

    async def products_list(
        self, callback: CallbackQuery, is_owner_admin: bool = False
    ) -> None:
        if not callback.data or not callback.message:
            return
        _, _, category_id_raw, page_raw = callback.data.split(":", maxsplit=3)
        category_id = int(category_id_raw)
        page = max(0, int(page_raw))
        category = await self.catalog.get_category(category_id)
        if category is None:
            await answer_callback_safely(
                callback, "Категорію не знайдено", show_alert=True
            )
            return

        category_name = category.name.strip().casefold()
        if category_name == "акції":
            promotions_url = await self.catalog.get_setting("promotions_url", "")
            text = (
                f"<b>{h(category.emoji)} {h(category.name)}</b>\n\n"
                "Тут налаштовується посилання на повідомлення в Telegram-каналі, "
                "де зібрані всі актуальні знижки.\n\n"
                f"Поточне посилання: <code>{h(promotions_url) if promotions_url else 'Не задано'}</code>"
            )
            await replace_with_text(
                callback.message,
                text,
                admin_kb.promotions_products_menu(category_id, bool(promotions_url)),
            )
            await answer_callback_safely(callback)
            return

        children = await self.catalog.list_categories(
            include_inactive=True, parent_id=category_id
        )
        total = await self.catalog.count_products(category_id)
        total_pages = max(1, math.ceil(total / PRODUCTS_PER_PAGE))
        page = min(page, total_pages - 1)
        products = await self.catalog.list_products(
            category_id,
            limit=PRODUCTS_PER_PAGE,
            offset=page * PRODUCTS_PER_PAGE,
        )
        currency = await self.catalog.get_setting("currency", "грн")
        text = (
            f"<b>{h(category.emoji)} {h(category.name)}</b>\n\n"
            f"Підкатегорій: {len(children)}\nТоварів: {total}"
        )
        if not products and not children:
            text += "\n\nТут поки порожньо."
        await replace_with_text(
            callback.message,
            text,
            admin_kb.category_contents(
                children,
                products,
                category_id=category_id,
                page=page,
                total_pages=total_pages,
                currency=currency,
                parent_id=category.parent_id,
                external_link_setting=(
                    "cartridges_url"
                    if category_name in {"картриджі", "картриджи"}
                    else None
                ),
            ),
        )
        await answer_callback_safely(callback)

    async def product_add_start(
        self, callback: CallbackQuery, state: FSMContext
    ) -> None:
        category_id = int((callback.data or "").rsplit(":", 1)[1])
        category = await self.catalog.get_category(category_id)
        if category is None:
            await answer_callback_safely(
                callback, "Категорію не знайдено", show_alert=True
            )
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
        await message.answer(
            "Надішліть бренд. Щоб залишити поле порожнім, надішліть <b>-</b>.",
            reply_markup=admin_kb.cancel(),
        )

    async def add_product_brand(self, message: Message, state: FSMContext) -> None:
        value = (message.text or "").strip()
        if len(value) > 80:
            await message.answer("Назва бренду надто довга.")
            return
        await state.update_data(brand="" if value == "-" else value)
        await state.set_state(AddProductStates.price)
        await message.answer(
            "Надішліть ціну числом, наприклад: <b>950</b> або <b>950.50</b>.",
            reply_markup=admin_kb.cancel(),
        )

    async def add_product_price(self, message: Message, state: FSMContext) -> None:
        value = normalize_price(message.text or "")
        if value is None:
            await message.answer(
                "Введіть ціну числом, наприклад: <b>950</b> або <b>950.50</b>."
            )
            return
        await state.update_data(price=value)
        await state.set_state(AddProductStates.description)
        await message.answer(
            "Надішліть опис товару. Щоб залишити поле порожнім, надішліть <b>-</b>.",
            reply_markup=admin_kb.cancel(),
        )

    async def add_product_description(
        self, message: Message, state: FSMContext
    ) -> None:
        value = (message.text or "").strip()
        if len(value) > 900:
            await message.answer("Опис надто довгий. Максимум 900 символів.")
            return
        await state.update_data(
            description="" if value == "-" else value,
            variant_type="none",
        )
        await state.set_state(AddProductStates.photo)
        await message.answer(
            "Надішліть фотографію товару або натисніть «Без фото».",
            reply_markup=admin_kb.photo_step(),
        )

    async def add_product_variant_type(
        self,
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
        value = (callback.data or "").rsplit(":", 1)[-1]
        if value not in VALID_VARIANT_TYPES:
            await answer_callback_safely(callback, "Невідомий тип", show_alert=True)
            return
        await state.update_data(variant_type=value)
        await state.set_state(AddProductStates.photo)
        if callback.message:
            await replace_with_text(
                callback.message,
                "Надішліть фотографію товару або натисніть «Без фото».",
                admin_kb.photo_step(),
            )
        await answer_callback_safely(callback)

    async def _finish_add_product(
        self, message: Message, state: FSMContext, photo_file_id: str | None
    ) -> None:
        data = await state.get_data()
        product_id = await self.catalog.add_product(
            category_id=int(data["category_id"]),
            name=str(data["name"]),
            brand=str(data["brand"]),
            price=str(data["price"]),
            description=str(data["description"]),
            photo_file_id=photo_file_id,
            variant_type=str(data.get("variant_type", "none")),
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
        await message.answer(
            "Потрібно надіслати саме фотографію або натиснути «Без фото».",
            reply_markup=admin_kb.photo_step(),
        )

    async def product_photo_skip(
        self, callback: CallbackQuery, state: FSMContext
    ) -> None:
        if callback.message:
            await self._finish_add_product(callback.message, state, None)
        await answer_callback_safely(callback)

    async def product_detail(
        self, callback: CallbackQuery, bot: Bot, is_owner_admin: bool = False
    ) -> None:
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

    async def product_variant_type_edit_start(
        self,
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
        product_id = int((callback.data or "").rsplit(":", 1)[1])
        product = await self.catalog.get_product(product_id)
        if product is None:
            await answer_callback_safely(callback, "Товар не знайдено", show_alert=True)
            return
        await state.clear()
        if callback.message:
            await replace_with_text(
                callback.message,
                "<b>Оберіть параметр, який покупець вводитиме при замовленні.</b>",
                admin_kb.variant_type_edit(product.id, product.variant_type),
            )
        await answer_callback_safely(callback)

    async def edit_product_variant_type(
        self,
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
        parts = (callback.data or "").split(":")
        if len(parts) != 4:
            await answer_callback_safely(callback, "Некоректна кнопка", show_alert=True)
            return
        product_id = int(parts[2])
        value = parts[3]
        if value not in VALID_VARIANT_TYPES:
            await answer_callback_safely(callback, "Невідомий тип", show_alert=True)
            return
        await self.catalog.update_product_field(product_id, "variant_type", value)
        await state.clear()
        product = await self.catalog.get_product(product_id)
        if product and callback.message:
            currency = await self.catalog.get_setting("currency", "грн")
            await replace_with_text(
                callback.message,
                "✅ Тип варіанта оновлено.\n\n" + admin_product_text(product, currency),
                admin_kb.product_actions(product, 0),
            )
        await answer_callback_safely(callback)

    async def product_edit_start(
        self, callback: CallbackQuery, state: FSMContext
    ) -> None:
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
            "quantity": "Надішліть кількість товару цілим числом. Наприклад: 12",
            "description": "Надішліть новий опис. Щоб очистити поле, надішліть -.",
            "photo_file_id": "Надішліть нову фотографію товару.",
        }
        await state.set_state(EditProductStates.value)
        await state.update_data(product_id=product_id, field=field)
        keyboard = (
            admin_kb.edit_photo(product_id)
            if field == "photo_file_id"
            else admin_kb.cancel()
        )
        if callback.message:
            await replace_with_text(callback.message, prompts[field], keyboard)
        await answer_callback_safely(callback)

    async def edit_product_photo(self, message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        if data.get("field") != "photo_file_id":
            await message.answer("У цьому полі потрібно надіслати текст.")
            return
        product_id = int(data["product_id"])
        await self.catalog.update_product_field(
            product_id, "photo_file_id", message.photo[-1].file_id
        )
        await state.clear()
        product = await self.catalog.get_product(product_id)
        currency = await self.catalog.get_setting("currency", "грн")
        if product:
            await message.answer(
                "✅ Фото оновлено.\n\n" + admin_product_text(product, currency),
                reply_markup=admin_kb.product_actions(product, 0),
            )

    async def edit_product_value(
        self, message: Message, state: FSMContext, is_owner_admin: bool = False
    ) -> None:
        data = await state.get_data()
        field = str(data.get("field", ""))
        product_id = int(data.get("product_id", 0))
        if field == "photo_file_id":
            await message.answer(
                "Надішліть фотографію, а не текст.",
                reply_markup=admin_kb.edit_photo(product_id),
            )
            return
        value = (message.text or "").strip()
        if field == "name" and not (2 <= len(value) <= 100):
            await message.answer("Назва має містити від 2 до 100 символів.")
            return
        if field == "brand" and len(value) > 80:
            await message.answer("Назва бренду надто довга.")
            return
        if field == "price":
            normalized_price = normalize_price(value)
            if normalized_price is None:
                await message.answer(
                    "Введіть ціну числом, наприклад: <b>950</b> або <b>950.50</b>."
                )
                return
            value = normalized_price
        if field == "description" and len(value) > 900:
            await message.answer("Опис надто довгий. Максимум 900 символів.")
            return
        if field == "quantity":
            if not value.isdigit() or int(value) > 999999:
                await message.answer("Введіть ціле число від 0 до 999999.")
                return
            await self.catalog.set_product_quantity(product_id, int(value))
            await state.clear()
            product = await self.catalog.get_product(product_id)
            currency = await self.catalog.get_setting("currency", "грн")
            if product:
                keyboard = admin_kb.product_actions(product, 0)
                await message.answer(
                    "✅ Кількість оновлено.\n\n"
                    + admin_product_text(product, currency),
                    reply_markup=keyboard,
                )
            return
        if field in {"brand", "description"} and value == "-":
            value = ""
        await self.catalog.update_product_field(product_id, field, value)
        await state.clear()
        product = await self.catalog.get_product(product_id)
        currency = await self.catalog.get_setting("currency", "грн")
        if product:
            keyboard = admin_kb.product_actions(product, 0)
            await message.answer(
                "✅ Товар оновлено.\n\n" + admin_product_text(product, currency),
                reply_markup=keyboard,
            )

    async def product_photo_delete(
        self, callback: CallbackQuery, state: FSMContext
    ) -> None:
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

    async def product_toggle(
        self, callback: CallbackQuery, bot: Bot, is_owner_admin: bool = False
    ) -> None:
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
            await answer_callback_safely(
                callback, "Товар уже видалено", show_alert=True
            )
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
    async def settings(self, callback: CallbackQuery, state: FSMContext) -> None:
        # Очищаємо будь-який незавершений сценарій редагування, інакше старий
        # FSM-стан може перехопити наступне повідомлення адміністратора.
        await state.clear()

        store_name = await self.catalog.get_setting(
            "store_name", "CrystalStore | Ковель"
        )
        currency = await self.catalog.get_setting("currency", "грн")
        contact_url = await self.catalog.get_setting("contact_url", "Не задано")
        promotions_url = await self.catalog.get_setting("promotions_url", "")
        cartridges_url = await self.catalog.get_setting("cartridges_url", "")
        flavors_url = await self.catalog.get_setting("flavors_url", "")
        colors_url = await self.catalog.get_setting("colors_url", "")

        text = (
            "<b>⚙️ Налаштування магазину</b>\n\n"
            f"Назва: {h(store_name)}\n"
            f"Валюта: {h(currency)}\n"
            f"Посилання продавця: {h(contact_url)}\n"
            f"Посилання на акції: {h(promotions_url) if promotions_url else 'Не задано'}\n"
            f"Посилання на картриджі: {h(cartridges_url) if cartridges_url else 'Не задано'}\n"
            f"Список смаків: {h(flavors_url) if flavors_url else 'Не задано'}\n"
            f"Список кольорів: {h(colors_url) if colors_url else 'Не задано'}\n\n"
            "Оберіть параметр для зміни."
        )
        if callback.message:
            await replace_with_text(callback.message, text, admin_kb.settings_menu())
        await answer_callback_safely(callback)

    async def setting_edit_start(
        self, callback: CallbackQuery, state: FSMContext
    ) -> None:
        key = (callback.data or "").split(":", maxsplit=2)[2]
        allowed = {
            "store_name",
            "welcome_text",
            "address_schedule",
            "contact_url",
            "promotions_url",
            "cartridges_url",
            "flavors_url",
            "colors_url",
            "currency",
            "age_warning",
        }
        if key not in allowed:
            await answer_callback_safely(
                callback, "Невідоме налаштування", show_alert=True
            )
            return
        current = await self.catalog.get_setting(key)
        await state.set_state(EditSettingStates.value)
        await state.update_data(key=key)

        if key == "promotions_url":
            prompt = (
                "<b>🔥 Посилання на повідомлення з акціями</b>\n\n"
                f"Поточне значення:\n<code>{h(current) if current else 'Не задано'}</code>\n\n"
                "Надішліть URL конкретного повідомлення у Telegram-каналі.\n"
                "Наприклад: <code>https://t.me/CrystalStoreKovel/123</code>"
            )
        elif key == "flavors_url":
            prompt = (
                "<b>💧 Посилання на список доступних смаків</b>\n\n"
                f"Поточне значення:\n<code>{h(current) if current else 'Не задано'}</code>\n\n"
                "Надішліть URL повідомлення у Telegram-каналі зі смаками рідин."
            )
        elif key == "colors_url":
            prompt = (
                "<b>🎨 Посилання на список доступних кольорів</b>\n\n"
                f"Поточне значення:\n<code>{h(current) if current else 'Не задано'}</code>\n\n"
                "Надішліть URL повідомлення у Telegram-каналі з кольорами POD-систем."
            )
        elif key == "cartridges_url":
            prompt = (
                "<b>🧩 Посилання на повідомлення з картриджами</b>\n\n"
                f"Поточне значення:\n<code>{h(current) if current else 'Не задано'}</code>\n\n"
                "Надішліть URL конкретного повідомлення у Telegram-каналі, "
                "де зібрані всі картриджі.\n"
                "Наприклад: <code>https://t.me/CrystalStoreKovel/456</code>"
            )
        else:
            prompt = (
                f"Поточне значення:\n<code>{h(current)}</code>\n\n"
                "Надішліть нове значення."
            )

        if callback.message:
            await replace_with_text(callback.message, prompt, admin_kb.cancel())
        await answer_callback_safely(callback)

    async def edit_setting_value(self, message: Message, state: FSMContext) -> None:
        value = (message.text or "").strip()
        data = await state.get_data()
        key = str(data["key"])
        if not value:
            await message.answer("Значення не може бути порожнім.")
            return
        if key in {
            "contact_url",
            "promotions_url",
            "cartridges_url",
            "flavors_url",
            "colors_url",
        } and not value.startswith(("https://", "http://", "tg://")):
            await message.answer(
                "Посилання має починатися з https://, http:// або tg://"
            )
            return
        await self.catalog.set_setting(key, value)
        await state.clear()

        if key == "promotions_url":
            categories = await self.catalog.list_categories(include_inactive=True)
            promotions_category = next(
                (
                    category
                    for category in categories
                    if category.name.strip().casefold() == "акції"
                ),
                None,
            )
            if promotions_category is not None:
                text = (
                    "✅ Посилання на акції збережено.\n\n"
                    f"<b>{h(promotions_category.emoji)} {h(promotions_category.name)}</b>\n\n"
                    f"Поточне посилання: <code>{h(value)}</code>"
                )
                await message.answer(
                    text,
                    reply_markup=admin_kb.promotions_products_menu(
                        promotions_category.id, True
                    ),
                )
                return

        if key == "cartridges_url":
            categories = await self.catalog.list_categories(include_inactive=True)
            cartridges_category = next(
                (
                    category
                    for category in categories
                    if category.name.strip().casefold() in {"картриджі", "картриджи"}
                ),
                None,
            )
            if cartridges_category is not None:
                text = (
                    "✅ Посилання на картриджі збережено.\n\n"
                    f"<b>{h(cartridges_category.emoji)} {h(cartridges_category.name)}</b>\n\n"
                    f"Поточне посилання: <code>{h(value)}</code>"
                )
                await message.answer(
                    text,
                    reply_markup=admin_kb.cartridges_products_menu(
                        cartridges_category.id, True
                    ),
                )
                return

        await message.answer(
            "✅ Налаштування збережено.", reply_markup=admin_kb.settings_menu()
        )

    # Inquiries and statistics
    async def requests(self, callback: CallbackQuery) -> None:
        inquiries = await self.inquiries.list_open()
        text = "<b>📝 Нові запити</b>\n\n"
        text += f"Відкритих запитів: <b>{len(inquiries)}</b>"
        if not inquiries:
            text += "\n\nНових запитів поки немає."
        if callback.message:
            await replace_with_text(
                callback.message, text, admin_kb.inquiries_list(inquiries)
            )
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
