"""Local marketplace search provider — queries the sellers' product collection."""
from app.core.logging import get_logger
from app.db import collections as col
from app.models.product_cache import RawProduct
from app.providers.base import BaseSearchProvider

logger = get_logger(__name__)


class LocalMarketplaceProvider(BaseSearchProvider):

    @property
    def source_name(self) -> str:
        return "local"

    async def search(
        self,
        keywords: list[str],
        category: str = "",
        price_min: float = 0.0,
        price_max: float = 0.0,
        limit: int = 100,
    ) -> list[RawProduct]:
        try:
            query: dict = {"is_active": True, "stock": {"$gt": 0}}

            if keywords:
                keyword_str = " ".join(keywords)
                query["$text"] = {"$search": keyword_str}

            if category:
                query["category"] = {"$regex": category, "$options": "i"}

            if price_min > 0:
                query.setdefault("price", {})["$gte"] = price_min
            if price_max > 0:
                query.setdefault("price", {})["$lte"] = price_max

            cursor = col.local_products().find(query).limit(limit)
            docs = await cursor.to_list(length=limit)

            results: list[RawProduct] = []
            for doc in docs:
                product_id = f"local_{doc['_id']}"
                results.append(RawProduct(
                    product_id=product_id,
                    source="local",
                    title=doc.get("title", ""),
                    price={"value": float(doc.get("price", 0)), "currency": doc.get("currency", "INR")},
                    url="",
                    image=doc.get("image", ""),
                    rating=float(doc.get("rating", 0)),
                    category=doc.get("category", ""),
                    raw_attributes={
                        "seller_id": doc.get("seller_id", ""),
                        "stock": doc.get("stock", 0),
                        "description": doc.get("description", ""),
                        "local_doc_id": str(doc["_id"]),
                    },
                ))

            logger.info("LocalProvider search", extra={"count": len(results), "keywords": keywords})
            return results

        except Exception as exc:
            logger.error("LocalProvider search error", extra={"error": str(exc)})
            return []
