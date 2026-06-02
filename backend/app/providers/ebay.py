"""eBay Finding API search provider."""
import hashlib
from typing import Any
import httpx

from app.core.config import settings
from app.core.constants import API_TIMEOUT_SECONDS
from app.core.logging import get_logger
from app.models.product_cache import RawProduct
from app.providers.base import BaseSearchProvider
from app.utils.retry import api_retry

logger = get_logger(__name__)


class EbayProvider(BaseSearchProvider):
    BASE_URL = "https://svcs.ebay.com/services/search/FindingService/v1"

    @property
    def source_name(self) -> str:
        return "ebay"

    def _make_product_id(self, item_id: str) -> str:
        return f"ebay_{item_id}"

    def _parse_item(self, item: dict[str, Any]) -> RawProduct | None:
        try:
            item_id = item.get("itemId", [None])[0]
            title = item.get("title", [""])[0]
            url = item.get("viewItemURL", [""])[0]
            image = item.get("galleryURL", [""])[0]
            category = item.get("primaryCategory", [{}])[0].get("categoryName", [""])[0]

            selling = item.get("sellingStatus", [{}])[0]
            price_info = selling.get("currentPrice", [{}])[0]
            price_value = float(price_info.get("__value__", 0))
            currency = price_info.get("@currencyId", "USD")

            condition = item.get("condition", [{}])[0]
            condition_name = condition.get("conditionDisplayName", [""])[0] if condition else ""

            return RawProduct(
                product_id=self._make_product_id(item_id),
                source="ebay",
                title=title,
                price={"value": price_value, "currency": currency},
                url=url,
                image=image,
                rating=0.0,
                category=category,
                raw_attributes={
                    "condition": condition_name,
                    "item_id": item_id,
                    "can_buy_here": False,
                    "redirect_url": url,
                    "cart_supported": True,
                },
            )
        except Exception as exc:
            logger.warning("Failed to parse eBay item", extra={"error": str(exc)})
            return None

    @api_retry
    async def search(
        self,
        keywords: list[str],
        category: str = "",
        price_min: float = 0.0,
        price_max: float = 0.0,
        limit: int = 100,
    ) -> list[RawProduct]:
        if not settings.ebay_app_id:
            logger.warning("EBAY_APP_ID not configured — using mock provider")
            from app.providers.mock import MockProvider
            return await MockProvider().search(keywords, category, price_min, price_max, limit)

        keyword_str = " ".join(keywords)
        params: dict[str, Any] = {
            "OPERATION-NAME": "findItemsByKeywords",
            "SERVICE-VERSION": "1.0.0",
            "SECURITY-APPNAME": settings.ebay_app_id,
            "RESPONSE-DATA-FORMAT": "JSON",
            "keywords": keyword_str,
            "paginationInput.entriesPerPage": min(limit, 100),
        }
        if price_min > 0:
            params["itemFilter(0).name"] = "MinPrice"
            params["itemFilter(0).value"] = price_min
            params["itemFilter(0).paramName"] = "Currency"
            params["itemFilter(0).paramValue"] = "USD"
        if price_max > 0:
            idx = 1 if price_min > 0 else 0
            params[f"itemFilter({idx}).name"] = "MaxPrice"
            params[f"itemFilter({idx}).value"] = price_max

        async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS) as client:
            resp = await client.get(self.BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        items = (
            data.get("findItemsByKeywordsResponse", [{}])[0]
            .get("searchResult", [{}])[0]
            .get("item", [])
        )
        
        #         {
        # "findItemsByKeywordsResponse": [
        #     {
        #     "searchResult": [
        #         {
        #         "item": [
        #             { "title": "Product 1" },
        #             { "title": "Product 2" }
        #         ]
        #         }
        #     ]
        #     }
        # ]
        # }

        results: list[RawProduct] = []
        for item in items:
            parsed = self._parse_item(item)
            if parsed:
                results.append(parsed)

        logger.info("eBay search completed", extra={"keyword": keyword_str, "count": len(results)})
        return results
