from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Category:
    id: int
    name: str
    emoji: str
    position: int
    active: bool


@dataclass(frozen=True, slots=True)
class Product:
    id: int
    category_id: int
    category_name: str
    category_emoji: str
    name: str
    brand: str
    price: str
    description: str
    photo_file_id: str | None
    in_stock: bool
    position: int


@dataclass(frozen=True, slots=True)
class Inquiry:
    id: int
    user_id: int
    username: str | None
    full_name: str
    product_id: int
    product_name: str
    product_price: str
    status: str
    created_at: str


@dataclass(frozen=True, slots=True)
class CatalogStats:
    categories: int
    products: int
    in_stock: int
    open_inquiries: int
