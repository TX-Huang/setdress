"""寫進資料庫那一層的測試。

重點全在「抓第二次會發生什麼事」。爬蟲會一直重跑，
重跑不能把資料弄亂，也不能把價格歷史寫出一堆重複列。
"""

import json
import pathlib

import pytest

from softgoods.models import Record
from softgoods.store import Store

SCHEMA = pathlib.Path(__file__).parent.parent / "schema.sql"


def rec(**kw) -> Record:
    base = {
        "site_id": "demo",
        "url": "https://demo.test/p/1",
        "title_raw": "Flos Bellhop 無線桌燈",
        "brand": "Flos",
        "model": "Bellhop",
        "cat1": "lighting",
        "cat2": "table",
        "variant_name": "Ø12.5 x 高 21 cm",
        "price": 7600,
    }
    base.update(kw)
    return Record(**base)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db", schema_path=SCHEMA)
    yield s
    s.close()


# ------------------------------------------------- 重跑不能弄亂資料


class TestIdempotent:
    def test_same_record_twice_makes_one_listing(self, store):
        store.upsert([rec()], seen_date="2026-11-20")
        store.upsert([rec()], seen_date="2026-11-20")
        assert store.count("listing") == 1
        assert store.count("product") == 1
        assert store.count("variant") == 1

    def test_unchanged_price_on_a_new_day_adds_no_history_row(self, store):
        store.upsert([rec(price=7600)], seen_date="2026-11-20")
        store.upsert([rec(price=7600)], seen_date="2026-11-21")
        assert store.count("price_point") == 1, "價格沒變就不要存，不然一年 365 列全一樣"

    def test_changed_price_adds_a_history_row(self, store):
        store.upsert([rec(price=7600)], seen_date="2026-11-20")
        store.upsert([rec(price=6900)], seen_date="2026-11-21")
        assert store.count("listing") == 1
        assert store.count("price_point") == 2

        rows = store.query(
            "SELECT seen_date, price FROM price_point ORDER BY seen_date"
        )
        assert rows == [("2026-11-20", 7600), ("2026-11-21", 6900)]

    def test_stock_change_also_counts_as_history(self, store):
        store.upsert([rec(price=7600, in_stock=False)], seen_date="2026-11-20")
        store.upsert([rec(price=7600, in_stock=True)], seen_date="2026-11-21")
        assert store.count("price_point") == 2

    def test_current_price_on_listing_is_the_latest(self, store):
        store.upsert([rec(price=7600)], seen_date="2026-11-20")
        store.upsert([rec(price=6900)], seen_date="2026-11-21")
        assert store.query("SELECT price FROM listing")[0][0] == 6900

    def test_last_seen_moves_forward(self, store):
        store.upsert([rec()], seen_date="2026-11-20")
        store.upsert([rec()], seen_date="2026-11-21")
        first, last = store.query("SELECT first_seen_at, last_seen_at FROM listing")[0]
        assert first.startswith("2026-11-20")
        assert last.startswith("2026-11-21")


# --------------------------------------------- 多個站賣同一款商品


class TestDedup:
    def test_two_sites_one_product(self, store):
        store.upsert(
            [
                rec(site_id="shop_a", url="https://a.test/x", price=7600),
                rec(site_id="shop_b", url="https://b.test/y", price=8200),
            ],
            seen_date="2026-11-20",
        )
        assert store.count("product") == 1, "同品牌同型號就是同一款"
        assert store.count("listing") == 2
        assert store.count("site") == 2

    def test_brand_spelling_differences_still_merge(self, store):
        aliases = {"flos": ["Flos", "FLOS", "Flos Italia"]}
        s = store
        s.brand_aliases = aliases
        s.upsert([rec(site_id="a", url="https://a.test/x", brand="FLOS")], seen_date="2026-11-20")
        s.upsert([rec(site_id="b", url="https://b.test/y", brand="Flos Italia")], seen_date="2026-11-20")
        assert s.count("brand") == 1
        assert s.count("product") == 1

    def test_different_variants_are_separate_rows(self, store):
        store.upsert(
            [
                rec(variant_name="Ø12.5 x 高 21 cm", url="https://demo.test/p/1"),
                rec(variant_name="Ø20 x 高 35 cm", url="https://demo.test/p/2"),
            ],
            seen_date="2026-11-20",
        )
        assert store.count("product") == 1
        assert store.count("variant") == 2
        assert store.count("listing") == 2

    def test_view_reports_price_range_across_sites(self, store):
        store.upsert(
            [
                rec(site_id="a", url="https://a.test/x", price=7600),
                rec(site_id="b", url="https://b.test/y", price=8200),
            ],
            seen_date="2026-11-20",
        )
        row = store.query(
            "SELECT price_min, price_max, site_count FROM v_product_price"
        )[0]
        assert row == (7600, 8200, 2)


# ------------------------------------------------------ 正規化有生效


class TestNormalizationApplied:
    def test_dimensions_are_stored_in_mm(self, store):
        store.upsert([rec(variant_name="Ø12.5 x 高 21 cm")], seen_date="2026-11-20")
        dia, h, raw = store.query(
            "SELECT diameter_mm, height_mm, size_raw FROM variant"
        )[0]
        assert (dia, h) == (125, 210)
        assert raw == "Ø12.5 x 高 21 cm", "原始字串要留著，換算錯了才回溯得到"

    def test_category_specific_attrs_go_into_json(self, store):
        store.upsert(
            [rec(product_attrs={"voltage": "全電壓、110V", "lumens": 450})],
            seen_date="2026-11-20",
        )
        attrs = json.loads(store.query("SELECT attrs FROM product")[0][0])
        assert attrs["voltage"] == "全電壓、110V"
        assert attrs["lumens"] == 450

    def test_json_attrs_are_queryable(self, store):
        store.upsert([rec(product_attrs={"voltage": "全電壓、110V"})], seen_date="2026-11-20")
        rows = store.query(
            "SELECT model FROM product WHERE json_extract(attrs,'$.voltage') LIKE '%110%'"
        )
        assert rows == [("Bellhop",)]

    def test_lead_time_is_parsed_from_stock_text(self, store):
        store.upsert([rec(stock_text="預購 6 - 8 個月")], seen_date="2026-11-20")
        days, raw = store.query("SELECT lead_time_days, stock_text FROM listing")[0]
        assert days == 180
        assert raw == "預購 6 - 8 個月"


# ------------------------------------------------- 真正能比價的 view


class TestSameSpecComparison:
    """v_product_price 的 min..max 是「整個系列」的範圍，不是價差。

    Artemide Tolomeo 底下有夾燈、Micro 桌燈、Mega 立燈、XXL 戶外立燈，
    12,600 到 786,400 是不同的產品。要比價得同款 + 同型式 + 同尺寸。
    """

    def test_same_product_same_size_two_sites_is_comparable(self, store):
        store.upsert(
            [
                rec(site_id="a", url="https://a.test/x", price=7600,
                    variant_name="桌燈 · Ø12.5 x 高 21 cm"),
                rec(site_id="b", url="https://b.test/y", price=8200,
                    variant_name="桌燈 · Ø12.5 x 高 21 cm"),
            ],
            seen_date="2026-11-20",
        )
        rows = store.query(
            "SELECT price_min, price_max, price_gap, site_count FROM v_same_spec_price"
        )
        assert rows == [(7600, 8200, 600, 2)]

    def test_different_sizes_are_never_compared(self, store):
        store.upsert(
            [
                rec(site_id="a", url="https://a.test/x", price=12600,
                    variant_name="桌燈 · Ø12 x 高 20 cm"),
                rec(site_id="b", url="https://b.test/y", price=786400,
                    variant_name="立燈 · 高 300 cm"),
            ],
            seen_date="2026-11-20",
        )
        assert store.count("v_same_spec_price") == 0, "不同尺寸的東西不該放在一起比價"

    def test_a_multipack_is_not_the_same_variant_as_the_single(self, store):
        """真實案例：Lee Broom Mini Crescent 單盞 31,100、五盞組 167,000，
        規格字串一模一樣（都是「吊燈 · Ø20 x H22 cm」）。"""
        store.upsert(
            [
                rec(url="https://a.test/1", title_raw="MINI CRESCENT 吊燈", price=31100,
                    variant_name="吊燈 · Ø20 x H22 cm", variant_attrs={"pack": 1}),
                rec(url="https://a.test/5", title_raw="MINI CRESCENT 五盞吊燈組", price=167000,
                    variant_name="吊燈 · Ø20 x H22 cm", variant_attrs={"pack": 5}),
            ],
            seen_date="2026-11-20",
        )
        assert store.count("variant") == 2, "尺寸一樣但組數不同，不是同一個規格"

    def test_a_multipack_is_never_compared_against_the_single(self, store):
        store.upsert(
            [
                rec(site_id="a", url="https://a.test/1", price=31100,
                    variant_name="吊燈 · Ø20 x H22 cm", variant_attrs={"pack": 1}),
                rec(site_id="b", url="https://b.test/5", price=167000,
                    variant_name="吊燈 · Ø20 x H22 cm", variant_attrs={"pack": 5}),
            ],
            seen_date="2026-11-20",
        )
        assert store.count("v_same_spec_price") == 0, "單盞不該跟五盞組比價"

    def test_one_site_only_is_not_a_comparison(self, store):
        store.upsert(
            [rec(variant_name="桌燈 · Ø12.5 x 高 21 cm")], seen_date="2026-11-20"
        )
        assert store.count("v_same_spec_price") == 0

    def test_unknown_size_is_left_out_rather_than_guessed(self, store):
        # 尺寸解析不出來就不要比。寧可少比，不要比錯。
        store.upsert(
            [
                rec(site_id="a", url="https://a.test/x", price=7600, variant_name="桌燈"),
                rec(site_id="b", url="https://b.test/y", price=99900, variant_name="桌燈"),
            ],
            seen_date="2026-11-20",
        )
        assert store.count("v_same_spec_price") == 0


# ------------------------------------------------------------ 下架


class TestGone:
    def test_listing_not_seen_this_run_is_marked_gone_not_deleted(self, store):
        store.upsert([rec(url="https://demo.test/p/1")], seen_date="2026-11-20")
        store.upsert([rec(url="https://demo.test/p/2")], seen_date="2026-11-21")
        store.mark_gone(site_id="demo", seen_date="2026-11-21")

        rows = dict(store.query("SELECT url, gone_at IS NOT NULL FROM listing"))
        assert rows["https://demo.test/p/1"] == 1, "沒看到了，標記下架"
        assert rows["https://demo.test/p/2"] == 0
        assert store.count("listing") == 2, "不要刪，歷史要留"

    def test_a_gone_listing_that_comes_back_is_revived(self, store):
        store.upsert([rec()], seen_date="2026-11-20")
        store.mark_gone(site_id="demo", seen_date="2026-11-21")
        store.upsert([rec()], seen_date="2026-11-22")
        assert store.query("SELECT gone_at FROM listing")[0][0] is None
