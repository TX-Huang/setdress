"""Adapter 的測試。

測試素材是真的從網站抓回來的檔案（tests/fixtures/），不是我編的。
編出來的 HTML 測不到真實世界的髒資料。
"""

import json
import pathlib

import pytest

from softgoods.adapters.lampclub import LampclubAdapter
from softgoods.adapters.shopify import ShopifyAdapter
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
