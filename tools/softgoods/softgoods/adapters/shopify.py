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
from dataclasses import replace

from .. import normalize as nz
from .. import sizes
from ..fetcher import Blocked, FetchError
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

    def crawl(self, fetch: Fetch) -> Iterator[Record]:
        for url in self.discover(fetch):
            pages: dict[str, str | None] = {}  # 同一個商品的幾個規格，商品頁只開一次（失敗也只試一次）
            for rec in self.parse(url, fetch(url)):
                yield self._size_from_page(rec, fetch, pages)

    def _needs_page(self, rec: Record) -> bool:
        """只有 size_from_page 的店、我們分得出類別的、清單裡又沒有尺寸的，才多開一頁。"""
        return (
            self.site.size_from_page
            and rec.cat1 != "unknown"
            and not nz.parse_dimensions(rec.size_raw)
        )

    @staticmethod
    def _product_page(url: str, fetch: Fetch, pages: dict[str, str | None]) -> str | None:
        """整頁很大（0.7 MB），存快取前先瘦身。抓不到回 None，不影響其他商品。"""
        if url not in pages:
            try:
                pages[url] = fetch(url, trim=sizes.slim_html)
            except (FetchError, Blocked):
                pages[url] = None
        return pages[url]

    def _size_from_page(self, rec: Record, fetch: Fetch, pages: dict[str, str | None]) -> Record:
        """潤舍的尺寸只在商品頁（Shopify 的 metafield，products.json 沒有）。見 SIZES.md。"""
        if not self._needs_page(rec):
            return rec
        page = self._product_page(rec.source_url, fetch, pages)
        snippet = sizes.size_snippet(page, rec.variant_name, rec.title_raw) if page else None
        snippet = snippet or sizes.title_size(rec.title_raw)
        return replace(rec, size_raw=snippet) if snippet else rec

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

    def _category(self, product: dict) -> tuple[str | None, str | None]:
        """先看 product_type；它太粗（只說「燈具」）就從標題補小分類。"""
        cat1, cat2 = nz.map_category(product.get("product_type"), self.category_map)
        if cat1 and not cat2:
            cat2 = nz.subcategory_from_title(product.get("title"), cat1, self.category_map)
        return cat1, cat2

    def _size_raw(self, product: dict, variant_name: str | None) -> str | None:
        """規格名有尺寸就用它；沒有就從介紹文字只抽尺寸那一段（SIZES.md）；再沒有才看標題。

        要開商品頁的店（size_from_page），標題留到商品頁之後：標題常常只寫一個方向（Ø40 cm）。
        """
        if nz.parse_dimensions(variant_name):
            return variant_name
        title = product.get("title")
        snippet = sizes.size_snippet(product.get("body_html"), variant_name, title)
        from_title = None if self.site.size_from_page else sizes.title_size(title)
        return snippet or from_title or variant_name

    def _variant_record(self, product: dict, variant: dict, images: list[str]) -> Record:
        brand = product.get("vendor") or ""
        model, color_hint = nz.clean_title(product.get("title", ""), brand)
        cat1, cat2 = self._category(product)
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
            size_raw=self._size_raw(product, variant_name),
            weight_g=variant.get("grams") or None,
            price=nz.parse_price(variant.get("price")),
            price_original=nz.parse_price(variant.get("compare_at_price")),
            currency=self.site.currency,
            sku=variant.get("sku") or None,
            in_stock=bool(variant.get("available")),
            is_official=self.site.kind == "brand_official",
            images=images,
            variant_image=(variant.get("featured_image") or {}).get("src") or None,
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
