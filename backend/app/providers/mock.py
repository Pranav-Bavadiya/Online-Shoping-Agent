"""Mock search provider — used when no real API key is configured."""
import random
from app.core.logging import get_logger
from app.models.product_cache import RawProduct
from app.providers.base import BaseSearchProvider

logger = get_logger(__name__)

MOCK_BRANDS = ["Samsung", "Sony", "Apple", "OnePlus", "Xiaomi", "Bose", "JBL", "LG"]
MOCK_CATEGORIES = ["Electronics", "Headphones", "Smartphones", "Laptops", "Accessories"]


class MockProvider(BaseSearchProvider):
    @property
    def source_name(self) -> str:
        return "mock"

    async def search(
        self,
        keywords: list[str],
        category: str = "",
        price_min: float = 0.0,
        price_max: float = 0.0,
        limit: int = 50,
    ) -> list[RawProduct]:
        keyword_str = " ".join(keywords) if keywords else "product"
        count = min(limit, 30)
        results: list[RawProduct] = []
        for i in range(count):
            brand = random.choice(MOCK_BRANDS)
            price = round(random.uniform(max(price_min, 200), max(price_max or 5000, 5000)), 2)
            pid = f"mock_{hash(keyword_str + str(i)) % 100000:05d}"
            results.append(RawProduct(
                product_id=pid,
                source="mock",
                title=f"{brand} {keyword_str.title()} Model-{i+1}",
                price={"value": price, "currency": "INR"},
                url=f"https://example.com/product/{pid}",
                image=f"https://via.placeholder.com/200?text={brand}",
                rating=round(random.uniform(3.0, 5.0), 1),
                category=category or random.choice(MOCK_CATEGORIES),
                raw_attributes={"brand": brand, "mock": True},
            ))
        logger.info("Mock search completed", extra={"count": len(results)})
        return results
