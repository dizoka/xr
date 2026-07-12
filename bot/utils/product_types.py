from __future__ import annotations

from dataclasses import dataclass

from bot.models import Product


VARIANT_NONE = "none"
VARIANT_COLOR = "color"
VARIANT_FLAVOR = "flavor"
VARIANT_CUSTOM = "custom"
VALID_VARIANT_TYPES = {VARIANT_NONE, VARIANT_COLOR, VARIANT_FLAVOR, VARIANT_CUSTOM}


@dataclass(frozen=True, slots=True)
class ProductOrderProfile:
    product_label: str
    variant_label: str | None
    variant_prompt: str | None
    variant_emoji: str = ""


def _normalized(value: str) -> str:
    return " ".join(
        value.strip().casefold().replace("_", " ").replace("-", " ").split()
    )


def infer_variant_type(category_name: str) -> str:
    category = _normalized(category_name)
    if any(
        marker in category
        for marker in ("pod", "под система", "под систем", "pod система", "pod систем")
    ) or category in {"системи", "системы"}:
        return VARIANT_COLOR
    if any(
        marker in category
        for marker in ("рідина", "рідини", "жидкость", "жидкости", "liquid", "juice")
    ):
        return VARIANT_FLAVOR
    return VARIANT_NONE


def variant_type_title(value: str) -> str:
    return {
        VARIANT_NONE: "Не запитувати",
        VARIANT_COLOR: "Колір",
        VARIANT_FLAVOR: "Смак",
        VARIANT_CUSTOM: "Інший варіант",
    }.get(value, "Не запитувати")


def order_profile(product: Product) -> ProductOrderProfile:
    explicit = _normalized(product.variant_type or "")
    variant_type = (
        explicit
        if explicit in VALID_VARIANT_TYPES
        else infer_variant_type(product.category_name)
    )

    if variant_type == VARIANT_COLOR:
        return ProductOrderProfile(
            product_label="POD-система",
            variant_label="Колір",
            variant_prompt="Вкажіть бажаний колір одним повідомленням.",
            variant_emoji="🎨",
        )
    if variant_type == VARIANT_FLAVOR:
        return ProductOrderProfile(
            product_label="Рідина",
            variant_label="Смак",
            variant_prompt="Вкажіть бажаний смак одним повідомленням.",
            variant_emoji="💧",
        )
    if variant_type == VARIANT_CUSTOM:
        return ProductOrderProfile(
            product_label="Товар",
            variant_label="Варіант",
            variant_prompt="Вкажіть потрібний варіант одним повідомленням.",
            variant_emoji="📝",
        )
    return ProductOrderProfile(
        product_label="Товар",
        variant_label=None,
        variant_prompt=None,
    )
