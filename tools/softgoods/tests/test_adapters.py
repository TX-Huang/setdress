"""Adapter 的測試。

測試素材是真的從網站抓回來的檔案（tests/fixtures/），不是我編的。
編出來的 HTML 測不到真實世界的髒資料。
"""

import json
import pathlib
from typing import ClassVar

import pytest

from softgoods import normalize as nz
from softgoods.adapters.lampclub import LampclubAdapter
from softgoods.adapters.shopify import ShopifyAdapter
from softgoods.fetcher import FetchError
from softgoods.models import SiteConfig
from softgoods.store import Store

FIX = pathlib.Path(__file__).parent / "fixtures"
SCHEMA = pathlib.Path(__file__).parent.parent / "schema.sql"

# lampclub 的頁面副本沒進 repo（授權範圍還沒確認，見 .gitignore），
# 所以 clone 下來的人不會有這兩個檔案。
# 讓它乾淨地 skip，不要變成一堆 error —— 否則接手的人會以為專案壞了。
LAMPCLUB_FIXTURES = ["lampclub_bellhop.html", "lampclub_beat.html"]
needs_lampclub = pytest.mark.skipif(
    not all((FIX / f).exists() for f in LAMPCLUB_FIXTURES),
    reason="lampclub 頁面副本沒進 repo（授權範圍未確認），見 .gitignore",
)


# =========================================================== Shopify
# 一支 adapter 打所有 Shopify 店 —— 這是省最多工的地方


@pytest.fixture
def shopify():
    return ShopifyAdapter(
        SiteConfig(
            site_id="luxurylife",
            name="潤舍 Luxury Life",
            base_url="https://www.luxurylife.com.tw",
            platform="shopify",
        )
    )


class TestShopifyAdapter:
    @pytest.fixture
    def records(self, shopify):
        body = (FIX / "shopify_products.json").read_text(encoding="utf-8")
        return shopify.parse("https://www.luxurylife.com.tw/products.json?page=1", body)

    def test_gets_one_record_per_variant(self, records):
        assert len(records) >= 3

    def test_reads_the_real_fields(self, records):
        r = records[0]
        assert r.brand == "Tom Dixon"
        assert r.price == 60200
        assert r.sku == "TOD00413"
        assert r.in_stock is False
        assert r.currency == "TWD"

    def test_keeps_the_original_title(self, records):
        assert records[0].title_raw == "【 展示品出清 】Tom Dixon Puff 吊燈 (黃銅)"

    def test_cleans_the_model_out_of_the_title(self, records):
        # 【展示品出清】、品牌名、結尾的分類詞都該去掉
        assert records[0].model == "Puff"

    def test_maps_product_type_to_our_taxonomy(self, records):
        # Shopify 的 product_type 是 '吊燈'
        assert (records[0].cat1, records[0].cat2) == ("lighting", "pendant")

    def test_a_broad_product_type_gets_the_subcategory_from_the_title(self, shopify):
        # 真實情況：NOSA 所有的燈 product_type 都是「燈具」，小分類只寫在標題
        product = {
            "id": 1, "handle": "zettelz-6", "vendor": "Ingo Maurer", "product_type": "燈具",
            "title": "Ingo Maurer - Zettel'z 6 吊燈",
            "variants": [{"id": 11, "title": "Default Title", "price": "52000.00", "available": True}],
        }
        recs = shopify.parse("https://x/products.json?page=1", json.dumps({"products": [product]}))
        assert (recs[0].cat1, recs[0].cat2) == ("lighting", "pendant")

    @staticmethod
    def _one_variant(shopify, variant_title: str, body_html: str, title: str = "Dutchbone-Beam 吊燈"):
        product = {
            "id": 2, "handle": "beam", "vendor": "Dutchbone", "product_type": "吊燈",
            "title": title, "body_html": body_html,
            "variants": [{"id": 21, "title": variant_title, "price": "9800.00", "available": True}],
        }
        return shopify.parse("https://x/products.json?page=1", json.dumps({"products": [product]}))[0]

    def test_size_comes_from_the_description_when_the_variant_has_none(self, shopify):
        # 真實情況（NOSA）：尺寸只寫在介紹文字裡。只留尺寸那一段（SIZES.md）
        body = "<p>介紹。</p><p>寬12 cm × 深65 cm × 高65 cm｜材質：Oak wood</p>"
        rec = self._one_variant(shopify, "米色", body)
        assert rec.size_raw == "寬12 cm × 深65 cm × 高65 cm"

    def test_the_title_size_is_used_when_nothing_else_has_one(self, shopify):
        rec = self._one_variant(shopify, "象牙白玻璃", "<p>只有介紹。</p>", title="New Works Lantern 桌燈 (Ø40 cm)")
        assert rec.size_raw == "New Works Lantern 桌燈 (Ø40 cm)"

    def test_a_size_in_the_variant_name_wins(self, shopify):
        body = "<p>尺寸：寬 30 x 高 40 cm</p>"
        rec = self._one_variant(shopify, "Ø19 x H28 cm", body)
        assert rec.size_raw == "Ø19 x H28 cm"

    @pytest.mark.parametrize(
        "product_type, want",
        [
            # 4 家 Shopify 店（2026-11-20）真實的 product_type
            ("吊燈 Pendant", ("lighting", "pendant")),
            ("桌燈 Table Lamp", ("lighting", "table")),
            ("無線桌燈 Wireless Table Lamp", ("lighting", "table")),
            ("戶外落地燈 Outdoor Floor Lamp", ("lighting", "outdoor")),
            ("Light燈飾", ("lighting", None)),
            ("燈具", ("lighting", None)),
            ("椅子 Chair", ("furniture", "chair")),
            ("Chair椅", ("furniture", "chair")),
            ("Sofa沙發", ("furniture", "sofa")),
            ("吧檯椅(高)", ("furniture", "chair")),
            ("Module模組層架", ("furniture", "storage")),
            ("家具", ("furniture", None)),
            ("家飾", ("decor", None)),
            ("香氛", ("decor", "scent")),
            ("地毯 Carpet", ("textile", "rug")),
            ("壁飾", ("decor", "wall_decor")),
        ],
    )
    def test_real_store_category_names_are_in_the_table(self, shopify, product_type, want):
        assert nz.map_category(product_type, shopify.category_map) == want

    def test_url_points_at_the_product_page_not_the_json(self, records):
        url = records[0].url
        assert "/products/" in url
        assert ".json" not in url, "listing 的網址要是人看的那一頁"

    def test_collects_images(self, records):
        assert records[0].images
        assert all(i.startswith("http") for i in records[0].images)

    def test_discover_paginates_and_stops_when_empty(self, shopify):
        pages = {
            "https://www.luxurylife.com.tw/products.json?limit=250&page=1": json.dumps(
                {"products": [{"id": 1, "title": "x", "handle": "x", "variants": [], "images": []}]}
            ),
            "https://www.luxurylife.com.tw/products.json?limit=250&page=2": json.dumps(
                {"products": []}
            ),
        }
        calls = []

        def fetch(u):
            calls.append(u)
            return pages[u]

        urls = list(shopify.discover(fetch))
        assert len(urls) == 1, "空的那頁不該被 yield 出去"
        assert len(calls) == 2, "要多打一次才知道沒了"


# ========================================================== lampclub
# HTML 的站：把原本 lamp_scraper.py 的邏輯搬進 adapter


class TestSizeFromProductPage:
    """潤舍：尺寸不在 products.json，在商品頁（SIZES.md）。sites.yaml 的 size_from_page 打開才去開。"""

    PRODUCT: ClassVar[dict] = {
        "id": 3, "handle": "bell", "vendor": "Tom Dixon", "product_type": "無線桌燈",
        "title": "Tom Dixon Bell 無線桌燈", "body_html": "<p>只有介紹，沒有尺寸。</p>",
        "variants": [
            {"id": 31, "title": "淺灰色", "price": "10600.00", "available": True},
            {"id": 32, "title": "橘紅色", "price": "10600.00", "available": True},
        ],
    }
    PAGE = "<p>商品資訊</p><p>尺寸：寬 19 x 深 28 x 高 28 cm</p>"

    def _crawl(self, *, size_from_page=True, product=None, page_error=False):
        site = SiteConfig(
            site_id="luxurylife", name="潤舍", base_url="https://www.luxurylife.com.tw",
            size_from_page=size_from_page,
        )
        calls = []

        def fetch(url, trim=None):
            calls.append((url, trim))
            if "products.json" in url:
                found = [product or self.PRODUCT] if "page=1" in url else []
                return json.dumps({"products": found})
            if page_error:
                raise FetchError("HTTP 404")
            return trim(self.PAGE) if trim else self.PAGE

        return list(ShopifyAdapter(site).crawl(fetch)), [c for c in calls if "products.json" not in c[0]]

    def test_reads_the_size_from_the_product_page(self):
        recs, pages = self._crawl()
        assert [r.size_raw for r in recs] == ["寬 19 x 深 28 x 高 28 cm"] * 2
        assert len(pages) == 1, "兩個規格，同一頁只開一次"
        assert pages[0][0] == "https://www.luxurylife.com.tw/products/bell"
        assert pages[0][1] is not None, "整頁太大，存快取前要瘦身"

    def test_off_by_default(self):
        recs, pages = self._crawl(size_from_page=False)
        assert pages == []
        assert recs[0].size_raw == "淺灰色"

    def test_skips_things_we_cannot_classify(self):
        # 水杯、包包不是軟裝，不用為了它們多開一頁
        _, pages = self._crawl(product={**self.PRODUCT, "product_type": "水杯"})
        assert pages == []

    def test_does_not_open_the_page_when_the_list_already_has_the_size(self):
        product = {**self.PRODUCT, "body_html": "<p>尺寸：寬 20 x 高 30 cm</p>"}
        recs, pages = self._crawl(product=product)
        assert pages == []
        assert recs[0].size_raw == "寬 20 x 高 30 cm"

    def test_a_page_that_fails_does_not_stop_the_crawl(self):
        recs, pages = self._crawl(page_error=True)
        assert len(recs) == 2
        assert len(pages) == 1, "失敗的頁面不要每個規格各打一次"
        assert recs[0].size_raw == "淺灰色"


@pytest.fixture
def lampclub():
    return LampclubAdapter(
        SiteConfig(site_id="lampclub", name="燈迷俱樂部", base_url="https://lampclub.tw")
    )


@needs_lampclub
class TestLampclubAdapter:
    @pytest.fixture
    def records(self, lampclub):
        body = (FIX / "lampclub_bellhop.html").read_text(encoding="utf-8")
        return lampclub.parse("https://lampclub.tw/lamps/flos-bellhop/", body)

    def test_one_record_per_row_in_the_buy_table(self, records):
        assert len(records) == 7

    def test_product_level_fields(self, records):
        r = records[0]
        assert r.brand == "Flos"
        assert r.model == "Bellhop"
        assert r.designer == "Edward Barber and Jay Osgerby"
        assert r.design_year == 2018
        assert r.cat1 == "lighting"

    def test_voltage_goes_into_attrs_not_a_column(self, records):
        assert "110V" in records[0].product_attrs["voltage"]

    def test_listing_level_fields(self, records):
        r = records[0]
        assert r.price == 7600
        assert "luxurylife.com.tw" in r.url, "要連到真正的通路，不是 lampclub 自己"
        assert r.stock_text
        assert r.size_raw

    def test_prices_are_all_parsed(self, records):
        assert all(r.price and r.price > 0 for r in records)

    def test_a_multi_channel_page_reports_several_sites(self, lampclub):
        body = (FIX / "lampclub_beat.html").read_text(encoding="utf-8")
        records = lampclub.parse("https://lampclub.tw/lamps/tom-dixon-beat/", body)
        assert len({r.channel for r in records}) >= 2
        assert records[0].brand == "Tom Dixon"

    def test_discover_reads_the_sitemap(self, lampclub):
        sitemap = (
            "<urlset>"
            "<url><loc>https://lampclub.tw/</loc></url>"
            "<url><loc>https://lampclub.tw/lamps/</loc></url>"
            "<url><loc>https://lampclub.tw/lamps/flos-bellhop/</loc></url>"
            "<url><loc>https://lampclub.tw/brands/flos/</loc></url>"
            "</urlset>"
        )
        urls = list(lampclub.discover(lambda u: sitemap))
        assert urls == ["https://lampclub.tw/lamps/flos-bellhop/"], "只要燈具頁"


# ============================================= 兩個 adapter 進同一個庫


@needs_lampclub
class TestBothAdaptersFeedOneDatabase:
    """這就是整個框架的重點：不同站的資料，進同一張表。"""

    def test_records_from_two_different_sites_load_together(self, tmp_path, shopify, lampclub):
        store = Store(tmp_path / "t.db", schema_path=SCHEMA)

        shop_recs = shopify.parse(
            "https://www.luxurylife.com.tw/products.json?page=1",
            (FIX / "shopify_products.json").read_text(encoding="utf-8"),
        )
        lamp_recs = lampclub.parse(
            "https://lampclub.tw/lamps/flos-bellhop/",
            (FIX / "lampclub_bellhop.html").read_text(encoding="utf-8"),
        )

        store.upsert(shop_recs, seen_date="2026-11-20")
        store.upsert(lamp_recs, seen_date="2026-11-20")

        assert store.count("listing") == len(shop_recs) + len(lamp_recs)
        assert store.count("site") >= 2
        # 兩邊都有 Tom Dixon / Flos，品牌表不該重複
        brands = {b for (b,) in store.query("SELECT name FROM brand")}
        assert "Flos" in brands
        store.close()


class TestTitleComesAfterTheProductPage:
    def test_a_page_store_opens_the_page_before_trusting_the_title(self):
        # 潤舍：標題「(Ø40 cm)」只有一個方向，商品頁有完整的寬深高
        site = SiteConfig(site_id="luxurylife", name="潤舍", base_url="https://www.luxurylife.com.tw",
                          size_from_page=True)
        product = {
            "id": 4, "handle": "lantern-40", "vendor": "New Works", "product_type": "桌燈",
            "title": "New Works Lantern 桌燈 (Ø40 cm)", "body_html": "<p>介紹。</p>",
            "variants": [{"id": 41, "title": "象牙白玻璃", "price": "9000.00", "available": True}],
        }

        def fetch(url, trim=None):
            if "products.json" in url:
                return json.dumps({"products": [product] if "page=1" in url else []})
            return "<p>尺寸：Ø40 x 高 42 cm</p>"

        recs = list(ShopifyAdapter(site).crawl(fetch))
        assert recs[0].size_raw == "Ø40 x 高 42 cm"
