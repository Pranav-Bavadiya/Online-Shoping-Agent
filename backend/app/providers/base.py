"""Abstract search provider interface."""
from abc import ABC, abstractmethod
from app.models.product_cache import RawProduct


class BaseSearchProvider(ABC):
    """All search providers must implement this interface."""

    @abstractmethod
    async def search(
        self,
        keywords: list[str],
        category: str = "",
        price_min: float = 0.0,
        price_max: float = 0.0,
        limit: int = 100,
    ) -> list[RawProduct]:
        """Execute a search and return raw products."""
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this provider (e.g. 'ebay')."""
        ...
