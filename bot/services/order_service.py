from __future__ import annotations

from dataclasses import dataclass

from bot.models import Inquiry, Product
from bot.repositories.catalog_repository import CatalogRepository
from bot.repositories.inquiry_repository import InquiryRepository
from bot.utils.ttl_cache import TTLCache


class ProductUnavailableError(RuntimeError):
    """Товар зник або закінчився під час оформлення."""


class DuplicateOrderError(RuntimeError):
    """Повторне натискання кнопки протягом кількох секунд."""


@dataclass(frozen=True, slots=True)
class CreatedOrder:
    product: Product
    inquiry: Inquiry
    created: bool


class OrderService:
    """Бізнес-логіка оформлення замовлення поза Telegram handler-ом."""

    def __init__(
        self,
        catalog: CatalogRepository,
        inquiries: InquiryRepository,
    ) -> None:
        self._catalog = catalog
        self._inquiries = inquiries
        self._recent_orders = TTLCache[tuple[int, int]](
            ttl_seconds=7,
            max_size=5_000,
        )

    async def create_order(
        self,
        *,
        user_id: int,
        username: str | None,
        full_name: str,
        product_id: int,
        variant_label: str,
        variant: str,
        request_key: str,
    ) -> CreatedOrder:
        recent_key = (user_id, product_id)
        if self._recent_orders.contains(recent_key):
            raise DuplicateOrderError("Замовлення вже створюється")
        self._recent_orders.add(recent_key)

        product = await self._catalog.get_product(product_id)
        if product is None or not product.in_stock or product.quantity <= 0:
            self._recent_orders.discard(recent_key)
            raise ProductUnavailableError("Цей товар уже недоступний")

        try:
            inquiry_id, created = await self._inquiries.create_snapshot(
                user_id=user_id,
                username=username,
                full_name=full_name,
                product=product,
                variant_label=variant_label,
                variant=variant,
                request_key=request_key,
            )
            inquiry = await self._inquiries.get(inquiry_id)
            if inquiry is None:
                raise RuntimeError("Створену заявку не знайдено")
            return CreatedOrder(product=product, inquiry=inquiry, created=created)
        except Exception:
            self._recent_orders.discard(recent_key)
            raise
