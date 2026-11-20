"""Shopline adapter —— 台灣很多設計家具、燈具通路用 Shopline。

跟 Shopify 不一樣的地方：

  - robots.txt 禁止 /api/，所以沒有「一次 250 個商品」的 JSON 清單可以打。
    只能從 sitemap 拿商品頁網址，一頁一頁開。
  - 每家都寫 Crawl-delay: 5，照它跑（fetcher 會自己讀 robots.txt）。
  - 商品資料在頁面的 <script> 裡：app.value('product', JSON.parse('…'))。
    JSON 被包成 JavaScript 字串，要拆兩層。
  - 沒有品牌、分類欄位：品牌看標題開頭（known_brands.txt），分類看標題裡的類別詞。
  - 整頁約 0.4 MB，存快取前先瘦身：只留商品資料和看得到的文字。

只存事實（policy.py）：介紹文字和圖片不收；尺寸從介紹文字裡只抽那一段（sizes.py）。
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
from .base import Adapter, Fetch, default_brand_names

_PRODUCT_RE = re.compile(r"app\.value\('product', JSON\.parse\('(.*?)(?<!\\)'\)\);", re.DOTALL)
_LDJSON_RE = re.compile(r'<script type="application/ld\+json">.*?</script>', re.DOTALL)
_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
_PRODUCT_PATH = re.compile(r"^/(?:(?P<locale>[a-z]{2}(?:-[a-z]+)?)/)?products/(?P<slug>[^/?#]+)")
_LEADING_TAGS = re.compile(r"^\s*(?:【[^】]*】|\[[^\]]*\]|［[^］]*］)\s*")
_LOCALE = "zh-hant"


# 快取裡只留這些欄位（商品資料原本約 30 KB，大半是圖片清單和金流、物流設定）
_KEEP_PRODUCT = (
    "_id", "title_translations", "field_titles", "variations", "price", "price_sale",
    "quantity", "unlimited_quantity", "out_of_stock_orderable", "sku", "brand", "status",
    "is_preorder", "sold_out",
)
_KEEP_VARIATION = ("key", "sku", "quantity", "fields_translations", "price", "price_sale")


def _js_string(text: str) -> str:
    """包回 JavaScript 字串（跟 Shopline 頁面一樣的寫法），讓 parse 走同一條路。"""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'").replace("</", "<\\/")


def _slim_product(product: dict) -> dict:
    out = {k: product[k] for k in _KEEP_PRODUCT if k in product}
    out["variations"] = [
        {k: v[k] for k in _KEEP_VARIATION if k in v} for v in product.get("variations") or []
    ]
    return out


def slim_product_page(page: str) -> str:
    """整頁（約 0.4 MB）→ 用得到的商品欄位 ＋ 看得到的文字和標籤骨架。存快取前用。"""
    product = _decode_product(page)
    data = _js_string(json.dumps(_slim_product(product), ensure_ascii=False)) if product else ""
    keep = f"<script>app.value('product', JSON.parse('{data}'));</script>" if product else ""
    return keep + sizes.slim_html(page)


def _decode_product(page: str) -> dict | None:
    """app.value('product', JSON.parse('…')) → dict。外層是 JavaScript 字串，裡面才是 JSON。"""
    m = _PRODUCT_RE.search(page)
    if not m:
        return None
    js = m.group(1).replace("\\'", "'").replace("\\`", "`").replace("\\$", "$")
    try:
        return json.loads(json.loads(f'"{js}"'))
    except (ValueError, TypeError):
        return None


def _text(value) -> str:
    """規格名是 list（["藍色"]），標題是字串。"""
    return " / ".join(x for x in value if x) if isinstance(value, list) else str(value or "")


def _zh(translations: dict | None) -> str:
    """多語系欄位挑中文；沒有就挑第一個有字的。"""
    options = [translations.get(_LOCALE), *translations.values()] if translations else []
    return next((t for t in map(_text, options) if t), "")


def _dollars(money: dict | None) -> int | None:
    """錢一律整數、四捨五入（跟 normalize.parse_price 一樣，不用 Python 的銀行家捨入）。"""
    amount = (money or {}).get("dollars") or 0
    return nz.parse_price(str(amount)) if amount > 0 else None


def _price_fields(source: dict) -> tuple[int | None, int | None]:
    """(售價, 原價)。有特價時售價是特價、原價留著。"""
    price, sale = _dollars(source.get("price")), _dollars(source.get("price_sale"))
    return (sale, price) if sale else (price, None)


def _stock_fields(product: dict, source: dict) -> tuple[bool, str | None]:
    in_stock = bool(product.get("unlimited_quantity")) or (source.get("quantity") or 0) > 0
    if in_stock:
        return True, None
    return False, "可預購" if product.get("out_of_stock_orderable") else "售完"


def _product_slug(url: str) -> str | None:
    """商品頁的代號。其他語言（/en/products/…）不要，跟中文版是同一件。"""
    m = _PRODUCT_PATH.match(urlparse(url).path)
    if not m or (m.group("locale") and m.group("locale") != _LOCALE):
        return None
    return m.group("slug")


def _pick_sitemap(subs: list[str]) -> str:
    """sitemap 目錄裡挑中文的那份；沒有就挑預設語言的；再沒有就第一份。"""
    ranked = [u for want in (f"locale={_LOCALE}", "locale=default") for u in subs if want in u]
    return (ranked or subs)[0]


def _variant_url(url: str, key: str | None) -> str:
    """每個規格一個網址（listing 靠網址分）。商品頁本身打得開，後面的參數 Shopline 不理。"""
    if not key:
        return url
    return f"{url}{'&' if '?' in url else '?'}variation={key}"


class ShoplineAdapter(Adapter):
    def __init__(self, site: SiteConfig, *args, brand_names: list[str] | None = None, **kwargs):
        super().__init__(site, *args, **kwargs)
        names = default_brand_names() if brand_names is None else brand_names
        self.brand_names = sorted(names, key=len, reverse=True)  # 長的先比：「Louis Poulsen」勝過「Louis」

    # ------------------------------------------------------------ 找商品頁

    def _sitemap_urls(self, fetch: Fetch) -> list[str]:
        """sitemap.xml；如果它是目錄（sitemapindex），開中文的那份。"""
        index = fetch(f"{self.site.base_url}/sitemap.xml")
        locs = [html.unescape(u) for u in _LOC_RE.findall(index)]
        if "<sitemapindex" not in index:
            return locs
        return [html.unescape(u) for u in _LOC_RE.findall(fetch(_pick_sitemap(locs)))]

    def discover(self, fetch: Fetch) -> Iterator[str]:
        """商品頁網址，同一件只取一次。"""
        seen: set[str] = set()
        for url in self._sitemap_urls(fetch):
            slug = _product_slug(url)
            if slug and slug not in seen:
                seen.add(slug)
                yield url

    def crawl(self, fetch: Fetch) -> Iterator[Record]:
        for url in self.discover(fetch):
            try:
                page = fetch(url, trim=slim_product_page)
            except (FetchError, Blocked):
                continue  # 一頁抓不到，不影響其他商品
            yield from self.parse(url, page)

    # ------------------------------------------------------------ 讀一頁

    def _brand(self, title: str) -> str:
        """標題開頭是已知品牌就是它；後面要接空白或符號，不能是字母（「Hayden」不是 HAY）。"""
        text = _LEADING_TAGS.sub("", title).casefold()
        for name in self.brand_names:
            after = text[len(name) : len(name) + 1]
            if text.startswith(name.casefold()) and not after.isalnum():
                return name
        return ""

    def _category(self, title: str) -> tuple[str | None, str | None]:
        """Shopline 沒有分類欄位，只能看標題：先照分類表對（「吸頂燈／壁燈」），對不到再找類別詞。"""
        cat1, cat2 = nz.map_category(title, self.category_map)
        if not cat1:
            return nz.category_from_title(title, self.category_map)
        return cat1, cat2 or nz.subcategory_from_title(title, cat1, self.category_map)

    @staticmethod
    def _size_raw(page: str, variant_name: str | None, title: str) -> str | None:
        if nz.parse_dimensions(variant_name):
            return variant_name
        return sizes.size_snippet(page, variant_name, title) or sizes.title_size(title) or variant_name

    def _record(self, url: str, page: str, product: dict, variation: dict | None) -> Record:
        title = _zh(product.get("title_translations"))
        brand = self._brand(title) or self.site.house_brand
        model, color_hint = nz.clean_title(title, brand)
        cat1, cat2 = self._category(title)
        source = variation or product
        variant_name = _zh(source.get("fields_translations")) or None
        price, price_original = _price_fields(source)
        in_stock, stock_text = _stock_fields(product, source)
        return Record(
            site_id=self.site.site_id,
            channel=self.site.name,
            url=_variant_url(url, source.get("key")),
            title_raw=title,
            brand=brand,
            model=model,
            cat1=cat1 or "unknown",
            cat2=cat2,
            variant_name=variant_name,
            color=variant_name if nz.color_family(variant_name) else color_hint,
            size_raw=self._size_raw(page, variant_name, title),
            price=price,
            price_original=price_original,
            currency=self.site.currency,
            sku=source.get("sku") or None,
            in_stock=in_stock,
            stock_text=stock_text,
            is_official=self.site.kind == "brand_official",
            source_site_id=self.site.site_id,
            source_url=url,
        )

    def parse(self, url: str, body: str) -> list[Record]:
        product = _decode_product(body)
        if not product:
            return []
        variations = product.get("variations") or [None]
        return [self._record(url, body, product, v) for v in variations]
