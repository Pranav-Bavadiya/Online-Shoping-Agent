"""Product lookup map DB model."""
from pydantic import BaseModel


class ProductLookupModel(BaseModel):
    product_id: str
    cache_doc_id: str  # _id of the product_cache document

    def to_doc(self) -> dict:
        return self.model_dump()
