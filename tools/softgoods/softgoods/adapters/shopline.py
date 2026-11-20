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
from .base import (
    Adapter,
    Fetch,
    brand_from_title,
    default_brand_names,
    longest_first,
    split_by_brand,
)

_PRODUCT_RE = re.compile(r"app\.value\('product', JSON\.parse\('(.*?)(?<!\\)'\)\);", re.DOTALL)
_LDJSON_RE = re.compile(r'<script type="application/ld\+json">.*?</script>', re.DOTALL)
_OBJECT_START = "app.value('product', {"
_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
_PRODUCT_PATH = re.compile(r"^/(?:(?P<locale>[a-z]{2}(?:-[a-z]+)?)/)?products/(?P<slug>[^/?#]+)")
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


def _only(data: dict, keys: tuple[str, ...]) -> dict:
    return {k: data[k] for k in keys if k in data}


def _media_url(media) -> str | None:
    """Shopline 的一張圖：{"images": {"original": {"url": …}}}。"""
    if not isinstance(media, dict):
        return None
    return ((media.get("images") or {}).get("original") or {}).get("url")


def _product_image_urls(product: dict) -> list[str]:
    urls = product.get("image_urls") or [_media_url(m) for m in product.get("media") or []]
    return [u for u in urls if u]


def _variation_image_url(variation: dict | None) -> str | None:
    variation = variation or {}
    return variation.get("image_url") or _media_url(variation.get("media"))


def _image_urls(product: dict, variation: dict | None) -> list[str]:
    """圖片連結：規格自己的照片排第一（做那個顏色的 3D 要用），再來是商品的；同一張不重複。"""
    urls = [_variation_image_url(variation), *_product_image_urls(product)]
    return list(dict.fromkeys(u for u in urls if u))


def _slim_product(product: dict) -> dict:
    """只留用得到的欄位；圖片只留原圖連結（媒體清單原本很大）。"""
    out = _only(product, _KEEP_PRODUCT)
    out["image_urls"] = _product_image_urls(product)
    out["variations"] = [
        {**_only(v, _KEEP_VARIATION), "image_url": _variation_image_url(v)}
        for v in product.get("variations") or []
    ]
    return out


def slim_product_page(page: str) -> str:
    """整頁（約 0.4 MB）→ 用得到的商品欄位 ＋ 看得到的文字和標籤骨架。存快取前用。"""
    product = _decode_product(page)
    data = _js_string(json.dumps(_slim_product(product), ensure_ascii=False)) if product else ""
    keep = f"<script>app.value('product', JSON.parse('{data}'));</script>" if product else ""
    return keep + sizes.slim_html(page)


def _decode_string_form(page: str) -> dict | None:
    """app.value('product', JSON.parse('…'))：外層是 JavaScript 字串，裡面才是 JSON。"""
    m = _PRODUCT_RE.search(page)
    if not m:
        return None
    js = m.group(1).replace("\\'", "'").replace("\\`", "`").replace("\\$", "$")
    try:
        return json.loads(json.loads(f'"{js}"'))
    except (ValueError, TypeError):
        return None


def _decode_object_form(page: str) -> dict | None:
    """app.value('product', {…})：直接寫成物件（Design Butik）。從 { 開始讀一個完整的 JSON 物件。"""
    start = page.find(_OBJECT_START)
    if start < 0:
        return None
    try:
        product, _ = json.JSONDecoder().raw_decode(page, start + len(_OBJECT_START) - 1)
    except ValueError:
        return None
    return product if isinstance(product, dict) else None


def _decode_product(page: str) -> dict | None:
    """Shopline 商品頁裡的商品資料。有兩種寫法，兩種都試。"""
    return _decode_string_form(page) or _decode_object_form(page)


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


def _pick_sitemaps(subs: list[str]) -> list[str]:
    """sitemap 目錄裡挑中文的那幾份（可能分好幾份）；沒有就挑預設語言的；再沒有就全部。"""
    for want in (f"locale={_LOCALE}", "locale=default"):
        hits = [u for u in subs if want in u]
        if hits:
            return hits
    return subs


def _variation_key(variation: dict | None, i: int) -> str | None:
    """規格的代號；沒有代號就用第幾個（不然兩個規格同一個網址，價格互相蓋掉）。"""
    if variation is None:
        return None
    return variation.get("key") or f"n{i}"


def _color(variant_name: str | None, color_hint: str | None) -> str | None:
    return variant_name if nz.color_family(variant_name) else color_hint


def _variant_url(url: str, key: str | None) -> str:
    """每個規格一個網址（listing 靠網址分）。商品頁本身打得開，後面的參數 Shopline 不理。"""
    if not key:
        return url
    return f"{url}{'&' if '?' in url else '?'}variation={key}"


class ShoplineAdapter(Adapter):
    def __init__(self, site: SiteConfig, *args, brand_names: list[str] | None = None, **kwargs):
        super().__init__(site, *args, **kwargs)
        names = default_brand_names() if brand_names is None else brand_names
        self.skipped = 0  # 這輪有幾頁抓不到或讀不懂（update.py 看這個決定算不算完整）
        self.brand_names = longest_first(names)

    # ------------------------------------------------------------ 找商品頁

    def _sitemap_urls(self, fetch: Fetch) -> list[str]:
        """sitemap.xml；如果它是目錄（sitemapindex），開中文的那份。"""
        index = fetch(f"{self.site.base_url}/sitemap.xml")
        locs = [html.unescape(u) for u in _LOC_RE.findall(index)]
        if "<sitemapindex" not in index:
            return locs
        return [
            html.unescape(u) for sub in _pick_sitemaps(locs) for u in _LOC_RE.findall(fetch(sub))
        ]

    def discover(self, fetch: Fetch) -> Iterator[str]:
        """商品頁網址，同一件只取一次。"""
        seen: set[str] = set()
        host = urlparse(self.site.base_url).netloc
        for url in self._sitemap_urls(fetch):
            if urlparse(url).netloc != host:
                continue  # sitemap 裡別的網站的網址不抓（那邊的 robots.txt 我們沒讀）
            slug = _product_slug(url)
            if slug and slug not in seen:
                seen.add(slug)
                yield url

    def crawl(self, fetch: Fetch) -> Iterator[Record]:
        """一頁抓不到或讀不懂，跳過但記下來（skipped）：這輪就不算完整，不標記下架。"""
        self.skipped = 0
        for url in self.discover(fetch):
            try:
                records = self.parse(url, fetch(url, trim=slim_product_page))
            except (FetchError, Blocked):
                records = []
            self.skipped += not records
            yield from records

    # ------------------------------------------------------------ 讀一頁

    def _brand(self, title: str) -> str:
        return brand_from_title(title, self.brand_names)

    def _known(self, name: str) -> str:
        """品牌在已知名單裡就用名單的寫法（「LOUIS POULSEN」→「Louis Poulsen」）。"""
        return next((n for n in self.brand_names if n.casefold() == name.casefold()), name)

    def _brand_and_model(self, title: str, field: str) -> tuple[str, str, str | None]:
        """品牌：商品資料的 brand 欄位 → 標題最後的「by 品牌」→ 標題開頭的已知品牌 → 店家自己的牌子。

        很多店的標題裡沒有品牌（WOW「Yama Coffee Table 咖啡桌」），但 brand 欄位有填（LAGO）。
        """
        core, by_brand = split_by_brand(title, self.brand_names)
        brand = self._known(field) if field else by_brand or self._brand(title) or self.site.house_brand
        model, color_hint = nz.clean_title(core, brand)
        return brand, model, color_hint

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

    def _record(self, url: str, page: str, product: dict, variation: dict | None, i: int = 0) -> Record:
        title = _zh(product.get("title_translations"))
        brand, model, color_hint = self._brand_and_model(title, _text(product.get("brand")).strip())
        cat1, cat2 = self._category(title)
        source = variation or product
        variant_name = _zh(source.get("fields_translations")) or None
        price, price_original = _price_fields(source)
        in_stock, stock_text = _stock_fields(product, source)
        return Record(
            site_id=self.site.site_id,
            channel=self.site.name,
            url=_variant_url(url, _variation_key(variation, i)),
            title_raw=title,
            brand=brand,
            model=model,
            cat1=cat1 or "unknown",
            cat2=cat2,
            variant_name=variant_name,
            color=_color(variant_name, color_hint),
            size_raw=self._size_raw(page, variant_name, title),
            price=price,
            price_original=price_original,
            currency=self.site.currency,
            sku=source.get("sku") or None,
            in_stock=in_stock,
            stock_text=stock_text,
            is_official=self.site.kind == "brand_official",
            images=_image_urls(product, variation),
            variant_image=_variation_image_url(variation),
            source_site_id=self.site.site_id,
            source_url=url,
        )

    def parse(self, url: str, body: str) -> list[Record]:
        product = _decode_product(body)
        if not product:
            return []
        variations = product.get("variations") or [None]
        return [self._record(url, body, product, v, i) for i, v in enumerate(variations)]
