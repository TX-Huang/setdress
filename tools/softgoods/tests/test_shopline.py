"""Shopline adapter 的測試。

頁面是照真實 Shopline 商品頁的結構自己做的（新采 2026-11-20 看過的格式），
文字是自己寫的 —— 不把店家的介紹文字放進公開 repo。

真實結構：
  - 商品資料放在 <script> 裡：app.value('product', JSON.parse('…'))，
    JSON 被包成 JavaScript 字串（" 變成 \\"、' 變成 \\'、</ 變成 <\\/）
  - 每個規格一筆 variations：fields_translations、price、price_sale、quantity、sku、key
  - 尺寸寫在頁面的介紹文字裡：「尺寸：Ø 140 × W 70 mm」
  - robots.txt 禁止 /api/，所以只能開商品頁
"""

import json

import pytest

from softgoods import normalize as nz
from softgoods.adapters.shopline import ShoplineAdapter, slim_product_page
from softgoods.models import SiteConfig

BASE = "https://www.shop.test"


def _money(dollars: float) -> dict:
    return {"cents": int(dollars * 100), "currency_iso": "TWD", "dollars": float(dollars)}


def variation(name: str, price: float, *, sale: float = 0, qty: int = 0, sku: str = "", key: str = "v1"):
    return {
        "key": key, "sku": sku, "quantity": qty,
        "fields_translations": {"en": [""], "zh-hant": [name]},
        "price": _money(price), "price_sale": _money(sale),
    }


def product(title: str, variations: list, **kw) -> dict:
    base = {
        "_id": "p1", "title_translations": {"zh-hant": title, "en": "Lamp"},
        "price": _money(0), "price_sale": _money(0), "quantity": 0, "sku": "",
        "unlimited_quantity": False, "out_of_stock_orderable": True,
        "variations": variations, "brand": "",
    }
    base.update(kw)
    return base


def js_string(text: str) -> str:
    """照 Rails escape_javascript 的方式包成 JavaScript 字串內容。"""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'").replace("</", "<\\/")


def page(prod: dict, description: str = "<h3><span>尺寸：Ø 140 × W 70 mm<br></span></h3>") -> str:
    data = js_string(json.dumps(prod, ensure_ascii=False))
    crumbs = {
        "@context": "http://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [{"@type": "ListItem", "position": 1, "name": "Home"},
                            {"@type": "ListItem", "position": 2, "name": "全部商品"}],
    }
    return (
        "<html><head><script>var tracking = '尺寸：寬 999 cm';</script>"
        f'<script type="application/ld+json">{json.dumps(crumbs, ensure_ascii=False)}</script>'
        f"<script>app.value('product', JSON.parse('{data}'));</script></head>"
        f'<body><nav class="menu">全部商品 燈具 家具</nav><div class="description">{description}</div>'
        "</body></html>"
    )


@pytest.fixture
def shopline():
    return ShoplineAdapter(
        SiteConfig(site_id="mithus", name="新采", base_url=BASE, adapter="shopline", platform="shopline"),
        brand_names=["Artemide", "Louis Poulsen", "HAY"],
    )


URL = f"{BASE}/zh-hant/products/artemide-teti"


class TestParse:
    def test_one_record_per_variation(self, shopline):
        prod = product("Artemide Teti 吸頂燈／壁燈", [variation("藍色", 5600, key="a"), variation("綠色", 5600, key="b")])
        recs = shopline.parse(URL, page(prod))
        assert [r.variant_name for r in recs] == ["藍色", "綠色"]
        assert [r.price for r in recs] == [5600, 5600]
        assert len({r.url for r in recs}) == 2, "每個規格的網址要不一樣（listing 靠網址分）"
        assert all(r.url.startswith(URL) for r in recs)

    def test_brand_model_and_category_come_from_the_title(self, shopline):
        recs = shopline.parse(URL, page(product("Artemide Teti 吸頂燈／壁燈", [variation("藍色", 5600)])))
        r = recs[0]
        assert r.brand == "Artemide"
        assert r.model == "Teti"
        assert (r.cat1, r.cat2) == ("lighting", "ceiling")

    def test_the_longest_brand_name_wins(self, shopline):
        recs = shopline.parse(URL, page(product("Louis Poulsen PH 5 吊燈", [variation("白色", 39000)])))
        assert recs[0].brand == "Louis Poulsen"

    def test_an_unknown_brand_is_left_empty(self, shopline):
        recs = shopline.parse(URL, page(product("無名小廠 方形邊桌", [variation("白色", 3000)])))
        assert recs[0].brand == ""

    def test_size_comes_from_the_description_not_from_scripts(self, shopline):
        recs = shopline.parse(URL, page(product("Artemide Teti 吸頂燈", [variation("藍色", 5600)])))
        assert recs[0].size_raw == "Ø 140 × W 70 mm"
        assert nz.parse_dimensions(recs[0].size_raw)["diameter_mm"] == 140

    def test_a_sale_price_is_the_price_and_the_old_one_is_kept(self, shopline):
        recs = shopline.parse(URL, page(product("HAY 邊桌", [variation("黑色", 8000, sale=6400)])))
        assert (recs[0].price, recs[0].price_original) == (6400, 8000)

    def test_stock(self, shopline):
        prod = product("HAY 邊桌", [variation("黑色", 8000, qty=3, key="a"), variation("白色", 8000, key="b")])
        recs = shopline.parse(URL, page(prod))
        assert [r.in_stock for r in recs] == [True, False]
        assert recs[1].stock_text == "可預購"

    def test_unlimited_quantity_is_in_stock(self, shopline):
        prod = product("HAY 邊桌", [variation("黑色", 8000)], unlimited_quantity=True)
        assert shopline.parse(URL, page(prod))[0].in_stock is True

    def test_a_product_without_variations_is_one_record(self, shopline):
        prod = product("HAY 邊桌", [], price=_money(5000), quantity=1)
        recs = shopline.parse(URL, page(prod))
        assert len(recs) == 1
        assert (recs[0].price, recs[0].in_stock, recs[0].url) == (5000, True, URL)

    def test_quotes_in_the_title_survive_the_javascript_wrapping(self, shopline):
        recs = shopline.parse(URL, page(product("HAY Kid's \"Mini\" 椅 </b>", [variation("紅", 1200)])))
        assert recs[0].title_raw == "HAY Kid's \"Mini\" 椅 </b>"

    def test_no_text_or_images_are_collected(self, shopline):
        r = shopline.parse(URL, page(product("HAY 邊桌", [variation("黑色", 8000)])))[0]
        assert r.description is None
        assert r.images == []

    def test_a_page_without_product_data_gives_nothing(self, shopline):
        assert shopline.parse(URL, "<html><body>找不到商品</body></html>") == []


class TestSlim:
    def test_keeps_the_product_data_and_visible_text_drops_other_scripts(self):
        raw = page(product("Artemide Teti 吸頂燈", [variation("藍色", 5600)]))
        slim = slim_product_page(raw)
        assert "app.value('product'" in slim
        assert "var tracking" not in slim
        assert "尺寸：Ø 140 × W 70 mm" in slim

    def test_parsing_the_slim_page_gives_the_same_records(self, shopline):
        raw = page(product("Artemide Teti 吸頂燈", [variation("藍色", 5600)]))
        assert shopline.parse(URL, slim_product_page(raw)) == shopline.parse(URL, raw)


SITEMAP_INDEX = f"""<?xml version="1.0"?><sitemapindex>
<sitemap><loc>{BASE}/sitemap.xml?locale=en</loc></sitemap>
<sitemap><loc>{BASE}/sitemap.xml?locale=zh-hant</loc></sitemap>
</sitemapindex>"""
SITEMAP_ZH = f"""<?xml version="1.0"?><urlset>
<url><loc>{BASE}/zh-hant/products/a</loc></url>
<url><loc>{BASE}/zh-hant/categories/lamps</loc></url>
<url><loc>{BASE}/zh-hant/products/b</loc></url>
<url><loc>{BASE}/zh-hant/products/a</loc></url>
</urlset>"""
SITEMAP_FLAT = f"""<?xml version="1.0"?><urlset>
<url><loc>{BASE}/products/a</loc></url>
<url><loc>{BASE}/en/products/a</loc></url>
<url><loc>{BASE}/products/b?x=1&amp;y=2</loc></url>
</urlset>"""


class TestDiscover:
    def test_reads_the_chinese_sitemap_and_keeps_only_products(self, shopline):
        pages = {f"{BASE}/sitemap.xml": SITEMAP_INDEX, f"{BASE}/sitemap.xml?locale=zh-hant": SITEMAP_ZH}
        got = list(shopline.discover(lambda url, trim=None: pages[url]))
        assert got == [f"{BASE}/zh-hant/products/a", f"{BASE}/zh-hant/products/b"]

    def test_a_flat_sitemap_skips_other_languages(self, shopline):
        got = list(shopline.discover(lambda url, trim=None: SITEMAP_FLAT))
        assert got == [f"{BASE}/products/a", f"{BASE}/products/b?x=1&y=2"]

    def test_crawl_opens_each_product_page_once_and_trims_it(self, shopline):
        prod_page = page(product("HAY 邊桌", [variation("黑色", 8000)]))
        calls = []

        def fetch(url, trim=None):
            calls.append((url, trim))
            if url.endswith("sitemap.xml"):
                return SITEMAP_INDEX
            if "locale=zh-hant" in url:
                return SITEMAP_ZH
            return trim(prod_page) if trim else prod_page

        recs = list(shopline.crawl(fetch))
        product_calls = [c for c in calls if "/products/" in c[0]]
        assert len(recs) == 2
        assert len(product_calls) == 2
        assert all(trim is slim_product_page for _, trim in product_calls)


class TestSlimDropsUnusedFields:
    def test_images_and_settings_are_not_kept(self):
        prod = product("HAY 邊桌", [variation("黑色", 8000)],
                       media=[{"images": {"original": {"url": "https://img.test/a.jpg"}}}],
                       blacklisted_payment_ids=["x"] * 50)
        slim = slim_product_page(page(prod))
        assert "img.test" not in slim
        assert "blacklisted_payment_ids" not in slim
        assert "title_translations" in slim


class TestHouseBrand:
    def test_a_single_brand_store_fills_in_its_own_brand(self):
        # 柒木只賣自己的燈，標題不會寫「柒木」；lampclub 寫的品牌是「柒木 KIMU design」
        site = SiteConfig(site_id="kimu", name="柒木", base_url=BASE, adapter="shopline",
                          house_brand="柒木 KIMU design")
        a = ShoplineAdapter(site, brand_names=["HAY"])
        recs = a.parse(URL, page(product("糖蔥II｜壁燈 金屬版", [variation("白", 4200)])))
        assert recs[0].brand == "柒木 KIMU design"

    def test_a_known_brand_in_the_title_still_wins(self):
        site = SiteConfig(site_id="x", name="x", base_url=BASE, adapter="shopline", house_brand="店家自己")
        a = ShoplineAdapter(site, brand_names=["HAY"])
        assert a.parse(URL, page(product("HAY 邊桌", [variation("黑", 8000)])))[0].brand == "HAY"
