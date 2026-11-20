"""通用讀取程式：sitemap ＋ schema.org Product（JSON-LD）。

很多自架網站（北歐櫥窗、Loft29）在商品頁放了給搜尋引擎看的標準商品資料：

    <script type="application/ld+json">{"@type": "Product", "name": …, "offers": {…}}</script>

讀這個就不用為每家寫 HTML 解析。加一家只要在 sites.yaml 寫：

    adapter: schemaorg
    product_url_pattern: /product/\\d+$     # sitemap 裡哪些網址是商品頁

  - 商品頁從 sitemap 拿（是目錄就每一份都讀），只留這個網站、符合 pattern 的
  - 品牌：Product.brand，沒有就看標題開頭（known_brands.txt），再沒有用 house_brand
  - 分類：麵包屑（最深的先），再看標題
  - 價格：offers.price；AggregateOffer 最低最高不一樣就不算價格（系列範圍不是價格）
  - 尺寸：頁面文字裡只抽尺寸那一段（sizes.py）；介紹文字、圖片不收（policy.py）
  - 存快取前瘦身：只留 JSON-LD 和看得到的文字
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from urllib.parse import urlparse

from .. import normalize as nz
from .. import sizes
from ..fetcher import Blocked, FetchError
from ..models import Record, SiteConfig
from .base import Adapter, Fetch, brand_from_title, default_brand_names, longest_first

_LD_RE = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
_LD_BLOCK_RE = re.compile(r"<script[^>]*application/ld\+json[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")

# availability 的最後一段（「https://schema.org/InStock」或「InStock」）→ (有貨, 說明)
_IN_STOCK = {"instock", "limitedavailability", "onlineonly", "instoreonly"}
_ORDERABLE = {"preorder", "presale", "backorder"}
_GONE = {"outofstock", "soldout", "discontinued"}


def slim_jsonld_page(page: str) -> str:
    """整頁 → JSON-LD 那幾段 ＋ 看得到的文字和標籤骨架。存快取前用。"""
    return "".join(_LD_BLOCK_RE.findall(page)) + sizes.slim_html(page)


def _flatten(data) -> list[dict]:
    """JSON-LD 可能是一個、一串、或包在 @graph 裡。"""
    if isinstance(data, list):
        return [item for d in data for item in _flatten(d)]
    if not isinstance(data, dict):
        return []
    return _flatten(data["@graph"]) if "@graph" in data else [data]


_WRAPPERS = re.compile(r"^\s*(?://\s*)?(?:<!--|<!\[CDATA\[)|(?://\s*)?(?:-->|\]\]>)\s*$")


def _unwrap(raw: str) -> str:
    """有些網站把 JSON-LD 包在 <!-- … --> 或 //<![CDATA[ … //]]> 裡。"""
    return _WRAPPERS.sub("", raw.strip()).strip()


def _ld_items(page: str) -> list[dict]:
    items: list[dict] = []
    for raw in _LD_RE.findall(page):
        try:
            items.extend(_flatten(json.loads(_unwrap(raw))))
        except ValueError:
            continue  # 壞掉的 JSON-LD 跳過，看其他段
    return items


def _is(item: dict, kind: str) -> bool:
    kinds = item.get("@type")
    return kind in (kinds if isinstance(kinds, list) else [kinds])


def _name(value) -> str:
    """品牌可能寫成 {"@type": "Brand", "name": "Vitra"}、直接 "Vitra"、或一串（取第一個有名字的）。"""
    if isinstance(value, list):
        return next((n for n in map(_name, value) if n), "")
    if isinstance(value, dict):
        return _name(value.get("name"))
    return str(value).strip() if isinstance(value, (str, int, float)) else ""


def _image_url(value) -> str | None:
    """一張圖可能寫成網址，或 {"@type": "ImageObject", "url" 或 "contentUrl": …}。"""
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl")
    return value if isinstance(value, str) and value.startswith(("http://", "https://")) else None


def _images(product: dict) -> list[str]:
    """圖片連結（只存連結，不下載；policy.py）。"""
    value = product.get("image")
    values = value if isinstance(value, list) else [value]
    return list(dict.fromkeys(u for u in map(_image_url, values) if u))


def _offers(product: dict) -> list[dict]:
    offers = product.get("offers")
    offers = offers if isinstance(offers, list) else [offers]
    return [o for o in offers if isinstance(o, dict)]


def _positive(value) -> int | None:
    """價格要是正數；0、空的、「NT$0」都當成沒價格（「歡迎來電洽詢」）。"""
    price = nz.parse_price(str(value)) if value not in (None, "") else None
    return price if price and price > 0 else None


def _range_price(offer: dict) -> int | None:
    """價格範圍（AggregateOffer、lowPrice/highPrice）：兩頭都有而且一樣才算（系列範圍不是價格）。"""
    low, high = _positive(offer.get("lowPrice")), _positive(offer.get("highPrice"))
    return low if low and low == high else None


def _is_range(offer: dict) -> bool:
    return _is(offer, "AggregateOffer") or "lowPrice" in offer or "highPrice" in offer


def _spec_price(offer: dict) -> int | None:
    """價格寫在 priceSpecification.price 裡的寫法。"""
    spec = offer.get("priceSpecification")
    return _positive(spec.get("price")) if isinstance(spec, dict) else None


def _price(offer: dict | None) -> int | None:
    if not offer:
        return None
    if _is_range(offer):
        return _range_price(offer)
    return _positive(offer.get("price")) or _spec_price(offer)


def _availability(offer: dict | None) -> tuple[bool | None, str | None]:
    value = str((offer or {}).get("availability") or "").rstrip("/").rsplit("/", 1)[-1].lower()
    if value in _IN_STOCK:
        return True, None
    if value in _ORDERABLE:
        return False, "可預購"
    if value in _GONE:
        return False, "售完"
    return None, None


def _crumb_name(element) -> str:
    """麵包屑一格的名字：寫在 name，或寫在 item.name（北歐櫥窗）。"""
    if not isinstance(element, dict):
        return ""
    item = element.get("item")
    inner = item.get("name") if isinstance(item, dict) else ""
    return str(element.get("name") or inner or "")


def _breadcrumbs(items: list[dict]) -> list[str]:
    crumbs = next((i for i in items if _is(i, "BreadcrumbList")), {})
    names = map(_crumb_name, crumbs.get("itemListElement") or [])
    return [n for n in names if n]


def _sku(offer: dict, product: dict) -> str | None:
    sku = offer.get("sku") or product.get("sku")
    return str(sku) if sku else None


def _listing_url(url: str, offer: dict, i: int, many: bool) -> str:
    """好幾個 offer 時每個一個網址（listing 靠網址分）；# 後面的部分不會送到網站。

    只用 offer 自己的 SKU：用商品的 SKU 的話，幾個 offer 會撞成同一個網址，價格互相蓋掉。
    """
    return f"{url}#v={offer.get('sku') or i}" if many else url


def _color(variant_name: str | None, color_hint: str | None) -> str | None:
    return variant_name if nz.color_family(variant_name) else color_hint


def _same_page(a: str, b: str) -> bool:
    """網址去掉 # 和結尾的 / 再比。"""
    return a.split("#")[0].rstrip("/") == b.split("#")[0].rstrip("/")


def _named_products(items: list[dict]) -> list[dict]:
    return [i for i in items if _is(i, "Product") and i.get("name")]


def _product_url(product: dict) -> str:
    return str(product.get("url") or product.get("@id") or "")


def _main_product(items: list[dict], url: str) -> dict | None:
    """這一頁的商品：url 或 @id 對得上這一頁的那個；都對不上就第一個（頁面上可能還有「相關商品」）。"""
    products = _named_products(items)
    if not products:
        return None
    return next((p for p in products if _same_page(_product_url(p), url)), products[0])


class SchemaOrgAdapter(Adapter):
    def __init__(self, site: SiteConfig, *args, brand_names: list[str] | None = None, **kwargs):
        super().__init__(site, *args, **kwargs)
        self.brand_names = longest_first(default_brand_names() if brand_names is None else brand_names)
        # 整條路徑都要符合（fullmatch）：「/blog/product/6」不是商品頁
        self.pattern = re.compile(site.product_url_pattern or r"/products?/[^/]+")
        self.host = urlparse(site.base_url).netloc
        self.skipped = 0  # 這輪有幾頁抓不到或讀不懂（update.py 看這個決定算不算完整）

    # ------------------------------------------------------------ 找商品頁

    def _locs(self, xml: str) -> list[str]:
        """sitemap 裡這個網站的網址（別的網站的不要：那邊的 robots.txt 我們沒讀）。"""
        urls = [html.unescape(u) for u in _LOC_RE.findall(xml)]
        return [u for u in urls if urlparse(u).netloc == self.host]

    def _sitemap_urls(self, fetch: Fetch) -> list[str]:
        index = fetch(f"{self.site.base_url}/sitemap.xml")
        locs = self._locs(index)
        if "<sitemapindex" not in index:
            return locs
        # 超過上限沒讀的那幾份：裡面的商品這輪沒看到，不能當成下架
        self.skipped += max(0, len(locs) - self.site.max_pages)
        return [u for part in locs[: self.site.max_pages] for u in self._locs(fetch(part))]

    def discover(self, fetch: Fetch) -> Iterator[str]:
        """sitemap 裡的商品頁（整條路徑符合 product_url_pattern），同一頁只取一次。

        網址的 ? 和 # 後面拿掉：「/product/6?utm_source=x」跟「/product/6」是同一件。
        """
        seen: set[str] = set()
        for url in self._sitemap_urls(fetch):
            parts = urlparse(url)
            page = f"{parts.scheme}://{parts.netloc}{parts.path}"
            if self.pattern.fullmatch(parts.path) and page not in seen:
                seen.add(page)
                yield page

    def crawl(self, fetch: Fetch) -> Iterator[Record]:
        """一頁抓不到或讀不懂，跳過但記下來（skipped）：這輪就不算完整，不標記下架。"""
        self.skipped = 0
        for url in self.discover(fetch):
            try:
                records = self.parse(url, fetch(url, trim=slim_jsonld_page))
            except (FetchError, Blocked):
                records = []
            self.skipped += not records
            yield from records

    # ------------------------------------------------------------ 讀一頁

    def _category(self, title: str, crumbs: list[str]) -> tuple[str | None, str | None]:
        """麵包屑（最深的先）、標題，誰先對到小分類就用誰。"""
        hits = [nz.map_category(t, self.category_map) for t in [*reversed(crumbs), title]]
        specific = next((h for h in hits if h[1]), None)
        return specific or self._from_broad(hits, title)

    def _from_broad(self, hits: list[tuple], title: str) -> tuple[str | None, str | None]:
        """只對到大分類就從標題補小分類；什麼都沒對到就在標題裡找類別詞。"""
        broad = next((h[0] for h in hits if h[0]), None)
        if not broad:
            return nz.category_from_title(title, self.category_map)
        return broad, nz.subcategory_from_title(title, broad, self.category_map)

    def _brand(self, product: dict, title: str) -> str:
        found = _name(product.get("brand")) or brand_from_title(title, self.brand_names)
        return found or self.site.house_brand

    @staticmethod
    def _size_raw(page: str, variant_name: str | None, title: str) -> str | None:
        if nz.parse_dimensions(variant_name):
            return variant_name
        return sizes.size_snippet(page, variant_name, title) or sizes.title_size(title) or variant_name

    def _record(self, url: str, page: str, product: dict, crumbs: list[str], offer, i: int, many: bool) -> Record:
        title = _name(product.get("name"))
        brand = self._brand(product, title)
        model, color_hint = nz.clean_title(title, brand)
        cat1, cat2 = self._category(title, crumbs)
        o = offer or {}
        variant_name = (_name(o.get("name")) or None) if many else None
        sku = _sku(o, product)
        in_stock, stock_text = _availability(offer)
        return Record(
            site_id=self.site.site_id,
            channel=self.site.name,
            url=_listing_url(url, o, i, many),
            title_raw=title,
            brand=brand,
            model=model,
            cat1=cat1 or "unknown",
            cat2=cat2,
            variant_name=variant_name,
            color=_color(variant_name, color_hint),
            size_raw=self._size_raw(page, variant_name, title),
            price=_price(offer),
            currency=o.get("priceCurrency") or self.site.currency,
            sku=sku,
            in_stock=in_stock,
            stock_text=stock_text,
            is_official=self.site.kind == "brand_official",
            images=_images(product),
            source_site_id=self.site.site_id,
            source_url=url,
        )

    def parse(self, url: str, body: str) -> list[Record]:
        items = _ld_items(body)
        product = _main_product(items, url)
        if not product:
            return []
        crumbs = _breadcrumbs(items)
        offers = _offers(product) or [None]
        many = len(offers) > 1
        return [self._record(url, body, product, crumbs, o, i, many) for i, o in enumerate(offers)]
