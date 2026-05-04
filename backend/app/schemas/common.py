from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    data: list[T]
    page: int = 1
    page_size: int = 20
    total: int = 0


class Envelope(BaseModel, Generic[T]):
    data: T | None = None
    errors: list[dict] | None = None
    meta: dict | None = None
