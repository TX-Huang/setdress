"""Shopify adapter —— 一支打所有 Shopify 店。

這是整個專案最省工的地方。Shopify 店都有一條公開的 JSON：

    /products.json?limit=250&page=N

一個請求 250 個商品，欄位乾淨（vendor / product_type / variants / images），
完全不用解析 HTML。台灣的設計家具燈飾通路很多是 Shopify 或 Shopline。

加一家新的 Shopify 店 = 在 sites.yaml 加三行，不用寫任何程式。
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from .. import normalize as nz
from ..models import Record
from .base import Adapter, Fetch

PAGE_SIZE = 250  # Shopify 的上限


class ShopifyAdapter(Adapter):
    def _page_url(self, page: int) -> str:
        return f"{self.site.base_url}/products.json?limit={PAGE_SIZE}&page={page}"

    def discover(self, fetch: Fetch) -> Iterator[str]:
        """一頁一頁往下翻，翻到空的就停。

        要先抓才知道有沒有東西，所以空的那一頁會多打一次 —— 無法避免。
        """
        for page in range(1, self.site.max_pages + 1):
            url = self._page_url(page)
            if not json.loads(fetch(url)).get("products"):
                return
            yield url

    @staticmethod
    def _product_attrs(product: dict) -> dict:
        """原始分類名一定要留。對不到的時候，你得查得出「網站寫的是哪個字」
        才知道要往 category_map.yaml 補什麼。"""
        return {
            "source_category": product.get("product_type") or None,
            "source_tags": product.get("tags") or None,
        }

    @staticmethod
    def _variant_label(variant: dict) -> str | None:
        """規格名稱可能在 title 或 option1。Shopify 的「沒有規格」長這樣。"""
        name = variant.get("title") or variant.get("option1")
        return None if name in ("Default Title", "Default", None, "") else name

    def _variant_record(self, product: dict, variant: dict, images: list[str]) -> Record:
        brand = product.get("vendor") or ""
        model, color_hint = nz.clean_title(product.get("title", ""), brand)
        cat1, cat2 = nz.map_category(product.get("product_type"), self.category_map)
        page_url = f"{self.site.base_url}/products/{product.get('handle', '')}"
        variant_name = self._variant_label(variant)

        return Record(
            site_id=self.site.site_id,
            channel=self.site.name,
            url=f"{page_url}?variant={variant.get('id')}",
            title_raw=product.get("title", ""),
            brand=brand,
            model=model,
            cat1=cat1 or "unknown",
            cat2=cat2,
            product_attrs=self._product_attrs(product),
            description=product.get("body_html") or None,
            variant_name=variant_name,
            color=(variant_name or "").strip("*") if nz.color_family(variant_name) else color_hint,
            size_raw=variant_name,
            weight_g=variant.get("grams") or None,
            price=nz.parse_price(variant.get("price")),
            price_original=nz.parse_price(variant.get("compare_at_price")),
            currency=self.site.currency,
            sku=variant.get("sku") or None,
            in_stock=bool(variant.get("available")),
            is_official=self.site.kind == "brand_official",
            images=images,
            source_site_id=self.site.site_id,
            source_url=page_url,
        )

    def parse(self, url: str, body: str) -> list[Record]:
        data = json.loads(body)
        out: list[Record] = []
        for product in data.get("products", []):
            images = [i["src"] for i in product.get("images", []) if i.get("src")]
            for variant in product.get("variants", []):
                out.append(self._variant_record(product, variant, images))
        return out
