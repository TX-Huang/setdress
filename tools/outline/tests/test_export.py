"""把自動描「可以用」的燈匯出成網站用的 catalog.js（export_catalog.py）。

驗收句子在 docs/catalog.md「資料」第 1 到 8 句。資料庫用最小的假資料庫，照片用畫的。
"""

import itertools
import json
import re
import sqlite3

import numpy as np
import pytest

import batch
import export_catalog as ex

SCHEMA = """
CREATE TABLE brand(brand_id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE site(site_id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE product(product_id TEXT PRIMARY KEY, brand_id INTEGER, model TEXT,
                     cat1 TEXT, cat2 TEXT);
CREATE TABLE variant(variant_id TEXT PRIMARY KEY, product_id TEXT, name TEXT,
                     width_mm REAL, depth_mm REAL, height_mm REAL, diameter_mm REAL, pack INTEGER);
CREATE TABLE listing(listing_id INTEGER PRIMARY KEY, variant_id TEXT, site_id TEXT, url TEXT,
                     price REAL, in_stock INTEGER, gone_at TEXT, last_seen_at TEXT);
"""


def make_db(path, variants, listings, cat2="pendant"):
    """variants: [(variant_id, 名稱, 寬, 深, 高, 直徑, 幾盞一組)]；
    listings: [(variant_id, 店, 價格, 有現貨, 下架日, 最後看到)]"""
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.execute("INSERT INTO brand VALUES (1, 'Louis Poulsen')")
    db.execute("INSERT INTO product VALUES ('lp__ph-5', 1, 'PH 5', 'lighting', ?)", (cat2,))
    for vid, name, w, d, h, dia, pack in variants:
        db.execute(
            "INSERT INTO variant VALUES (?, 'lp__ph-5', ?, ?, ?, ?, ?, ?)",
            (vid, name, w, d, h, dia, pack),
        )
    for i, (vid, store, price, stock, gone, seen) in enumerate(listings):
        db.execute("INSERT OR IGNORE INTO site VALUES (?, ?)", (store, store))
        url = f"https://{store}.example.com/products/ph-5?v={i}"
        db.execute(
            "INSERT INTO listing(variant_id, site_id, url, price, in_stock, gone_at, last_seen_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (vid, store, url, price, stock, gone, seen),
        )
    db.commit()
    db.close()
    return path


SEEN = "2026-11-20"


def offers_for(tmp_path, variants, listings, size=(50, 26.7)):
    db = make_db(tmp_path / "a.db", variants, listings)
    rows = ex.load_listings([db])["lp__ph-5"]
    return ex.offers(rows, size)


class TestOffers:
    def test_same_size_in_any_colour_counts(self, tmp_path):
        got = offers_for(
            tmp_path,
            [("white", "白", None, None, 267, 500, 1), ("black", "黑", None, None, 267, 500, 1)],
            [("white", "nosa", 39900, 1, None, SEEN), ("black", "jyt", 38000, None, None, SEEN)],
        )
        assert [(o["store"], o["price"], o["stock"]) for o in got] == [
            ("jyt", 38000, "unknown"),
            ("nosa", 39900, "in"),
        ]

    def test_another_size_does_not_count(self, tmp_path):
        got = offers_for(
            tmp_path,
            [("big", "Ø50", None, None, 267, 500, 1), ("mini", "Ø30", None, None, 160, 300, 1)],
            [("big", "nosa", 39900, 1, None, SEEN), ("mini", "jyt", 19000, 1, None, SEEN)],
        )
        assert [o["store"] for o in got] == ["nosa"]

    def test_no_size_counts_only_when_the_product_has_one_size(self, tmp_path):
        one = offers_for(
            tmp_path,
            [("big", "Ø50", None, None, 267, 500, 1), ("plain", "標準", None, None, None, None, 1)],
            [("big", "nosa", 39900, 1, None, SEEN), ("plain", "loft", 38000, 1, None, SEEN)],
        )
        assert [o["store"] for o in one] == ["loft", "nosa"]
        (tmp_path / "a.db").unlink()
        two = offers_for(
            tmp_path,
            [
                ("big", "Ø50", None, None, 267, 500, 1),
                ("mini", "Ø30", None, None, 160, 300, 1),
                ("plain", "標準", None, None, None, None, 1),
            ],
            [("big", "nosa", 39900, 1, None, SEEN), ("plain", "loft", 38000, 1, None, SEEN)],
        )
        assert [o["store"] for o in two] == ["nosa"], "兩種尺寸時，沒標尺寸的不知道是哪一個"

    def test_packs_gone_and_priceless_listings_do_not_count(self, tmp_path):
        got = offers_for(
            tmp_path,
            [("one", "1 盞", None, None, 267, 500, 1), ("set", "2 盞組", None, None, 267, 500, 2)],
            [
                ("one", "nosa", 39900, 1, None, SEEN),
                ("set", "jyt", 70000, 1, None, SEEN),
                ("one", "gone", 30000, 1, "2026-11-19", SEEN),
                ("one", "free", None, 1, None, SEEN),
            ],
        )
        assert [o["store"] for o in got] == ["nosa"]

    def test_the_cheapest_price_per_store_with_its_link_and_stock(self, tmp_path):
        got = offers_for(
            tmp_path,
            [("a", "白", None, None, 267, 500, 1), ("b", "黑", None, None, 267, 500, 1)],
            [("a", "nosa", 39900, 1, None, SEEN), ("b", "nosa", 37000, 0, None, SEEN)],
        )
        assert len(got) == 1
        assert (got[0]["price"], got[0]["stock"]) == (37000, "out")
        assert got[0]["url"].startswith("https://nosa.example.com/")


# ---------------------------------------------------------------- 顏色
BG = (185, 190, 200)


def two_colour(dark_share=0.4, h=300, w=200):
    """灰底上的圓柱：底下 dark_share 是深色金屬，上面是米白色燈罩。"""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = BG
    top, bottom = 40, 260
    split = round(bottom - dark_share * (bottom - top))
    img[top:split, 60:140] = (238, 228, 205)
    img[split : bottom + 1, 60:140] = (45, 42, 40)
    return img


class TestBands:
    def test_two_colours_make_two_bands_with_the_right_material(self):
        bands = ex.bands(two_colour(0.4), height_cm=50)
        assert [b["m"] for b in bands] == ["metal", "shade"]
        assert bands[0]["to"] == pytest.approx(20, abs=1.5), "金屬到全高的 40%"
        assert bands[-1]["to"] == pytest.approx(50, abs=0.01)
        assert bands[0]["c"] == 0x2D2A28
        assert bands[1]["c"] == 0xEEE4CD

    def test_one_colour_is_one_band(self):
        img = two_colour(0.0)
        assert len(ex.bands(img, height_cm=50)) == 1

    def test_noise_does_not_make_extra_bands(self):
        img = two_colour(0.4).astype(int)
        noise = np.random.default_rng(1).integers(-12, 13, img.shape)
        img = np.clip(img + noise, 0, 255).astype(np.uint8)
        img[:40], img[261:], img[:, :60], img[:, 140:] = BG, BG, BG, BG  # 背景保持乾淨
        assert len(ex.bands(img, height_cm=50)) == 2

    def test_at_most_four_bands_each_at_least_a_tenth(self):
        img = np.zeros((300, 200, 3), dtype=np.uint8)
        img[:] = BG
        stripes = [
            (30, 30, 30),
            (240, 240, 240),
            (200, 40, 40),
            (40, 40, 200),
            (240, 240, 240),
            (30, 30, 30),
        ]
        for i, colour in enumerate(stripes):  # 6 條，每條 30 列
            img[40 + 30 * i : 70 + 30 * i, 60:140] = colour
        bands = ex.bands(img, height_cm=60)
        assert 2 <= len(bands) <= 4
        tops = [0] + [b["to"] for b in bands]
        assert all(b - a >= 6 - 1e-6 for a, b in itertools.pairwise(tops)), "每段至少一成"

    def test_a_thin_ring_is_not_its_own_band(self):
        img = two_colour(0.0)
        img[150:159, 60:140] = (30, 30, 30)  # 220 列裡 9 列（4%）的深色細環
        bands = ex.bands(img, height_cm=50)
        tops = [0] + [b["to"] for b in bands]
        assert all(b - a >= 5 - 1e-6 for a, b in itertools.pairwise(tops)), "每段至少全高的一成"

    def test_smooth_shading_on_one_material_stays_one_band(self):
        img = two_colour(0.0)
        for i, row in enumerate(range(40, 261)):  # 燈罩由上往下從亮到暗一點（光線的明暗）
            img[row, 60:140] = np.array([238, 228, 205]) - round(30 * i / 220)
        assert len(ex.bands(img, height_cm=50)) == 1

    def test_light_colours_are_shade_and_dark_or_strong_ones_are_metal(self):
        assert ex.material((240, 210, 40)) == "metal"  # 很亮但很鮮豔：芥黃烤漆
        assert ex.material((240, 238, 230)) == "shade"
        assert ex.material((215, 200, 170)) == "shade"  # 米色紙燈罩
        assert ex.material((200, 40, 40)) == "metal"  # 紅色烤漆
        assert ex.material((180, 140, 70)) == "metal"  # 黃銅
        assert ex.material((40, 40, 40)) == "metal"


class TestLight:
    def test_a_pendant_light_sits_at_the_widest_layer(self):
        globe = [[2, 0], [10, 5], [15, 12], [10, 20], [1, 25]]
        light, beam = ex.light_and_beam(globe, "pendant")
        assert light == [0, 12, 0] and beam == "all"

    def test_a_pendant_open_at_the_bottom_shines_down(self):
        dome = [[20, 0], [18, 8], [10, 15], [2, 18]]
        assert ex.light_and_beam(dome, "pendant") == ([0, 0, 0], "down")

    def test_a_table_lamp_ignores_a_wide_base(self):
        lamp = [[12, 0], [12, 2], [2, 3], [2, 30], [10, 32], [9, 45], [1, 46]]
        light, beam = ex.light_and_beam(lamp, "table")
        assert light == [0, 32, 0] and beam == "all"


# ---------------------------------------------------------------- 整份檔案
def outline_db(path, rows):
    out = batch.Results(path)
    for pid, status, vid, w, h, lathe in rows:
        out.save(
            batch.Result(
                pid, status, image_url="u", variant_id=vid, width_cm=w, height_cm=h, lathe=lathe
            )
        )
    out.db.close()
    return path


LATHE = [[5, 0], [25, 8], [16, 12], [4, 21], [1, 26.7]]


class TestCatalog:
    def build(self, tmp_path, status="ok"):
        db = make_db(
            tmp_path / "a.db",
            [("white", "白", None, None, 267, 500, 1)],
            [("white", "nosa", 39900, 1, None, SEEN)],
        )
        outlines = outline_db(tmp_path / "o.db", [("lp__ph-5", status, "white", 50, 26.7, LATHE)])
        return ex.build([db], outlines, photo_for=lambda url: None)

    def test_only_ok_outlines_are_included(self, tmp_path):
        assert [e["id"] for e in self.build(tmp_path)["lamps"]] == ["c:lp__ph-5"]
        (tmp_path / "a.db").unlink()
        (tmp_path / "o.db").unlink()
        assert self.build(tmp_path, status="suspect")["lamps"] == []

    def test_an_entry_has_everything_the_simulator_needs(self, tmp_path):
        e = self.build(tmp_path)["lamps"][0]
        assert (e["brand"], e["name"], e["variant"], e["category"], e["mount"]) == (
            "Louis Poulsen",
            "PH 5",
            "白",
            "吊燈",
            "pendant",
        )
        assert e["size"] == {"w": 50, "h": 26.7}
        assert e["lathe"] == LATHE
        assert e["bands"][-1]["to"] == pytest.approx(26.7)
        assert e["light"][0] == 0 and e["beam"] in ("all", "down")
        assert e["offers"][0]["store"] == "nosa"

    def test_without_a_photo_the_colour_is_one_grey_metal_band(self, tmp_path):
        bands = self.build(tmp_path)["lamps"][0]["bands"]
        assert len(bands) == 1 and bands[0]["m"] == "metal"

    def test_the_file_is_the_same_every_time_and_has_no_photos(self, tmp_path):
        data = self.build(tmp_path)
        a, b = tmp_path / "a.js", tmp_path / "b.js"
        ex.write(data, a)
        ex.write(json.loads(json.dumps(data)), b)
        assert a.read_bytes() == b.read_bytes()
        text = a.read_text(encoding="utf-8")
        assert not re.search(r"\.(jpe?g|png|webp|gif)\b|image|photo", text, re.I), (
            "照片和照片連結不上網站"
        )
        assert "SetdressCatalog" in text


class TestVariantName:
    def test_a_placeholder_variant_name_is_left_out(self, tmp_path):
        for placeholder in ("標準", "Default Title"):
            db = make_db(
                tmp_path / "a.db",
                [("v", placeholder, None, None, 267, 500, 1)],
                [("v", "nosa", 39900, 1, None, SEEN)],
            )
            outlines = outline_db(tmp_path / "o.db", [("lp__ph-5", "ok", "v", 50, 26.7, LATHE)])
            entry = ex.build([db], outlines, photo_for=lambda url: None)["lamps"][0]
            assert entry["variant"] == "", placeholder
            (tmp_path / "a.db").unlink()
            (tmp_path / "o.db").unlink()


class TestColourNames:
    """照片是商品的第一張，不知道是哪個顏色款式。

    好幾個顏色時，不寫款式的顏色名（docs/catalog.md 第 10 句）。
    """

    def entry(self, tmp_path, variants):
        db = make_db(tmp_path / "a.db", variants, [(variants[0][0], "nosa", 39900, 1, None, SEEN)])
        outlines = outline_db(
            tmp_path / "o.db", [("lp__ph-5", "ok", variants[0][0], 50, 26.7, LATHE)]
        )
        return ex.build([db], outlines, photo_for=lambda url: None)["lamps"][0]

    def test_a_colour_name_is_left_out_when_there_are_other_colours(self, tmp_path):
        e = self.entry(
            tmp_path,
            [("w", "白色", None, None, 267, 500, 1), ("b", "黑色", None, None, 267, 500, 1)],
        )
        assert e["variant"] == ""

    def test_the_only_variant_keeps_its_colour_name(self, tmp_path):
        assert self.entry(tmp_path, [("w", "白色", None, None, 267, 500, 1)])["variant"] == "白色"

    def test_a_name_without_a_colour_is_kept(self, tmp_path):
        e = self.entry(
            tmp_path,
            [("s", "Ø50 cm", None, None, 267, 500, 1), ("m", "Ø30 cm", None, None, 160, 300, 1)],
        )
        assert e["variant"] == "Ø50 cm"

    def test_english_colour_words_count_too(self, tmp_path):
        e = self.entry(
            tmp_path,
            [("w", "Matt White", None, None, 267, 500, 1), ("b", "Black", None, None, 267, 500, 1)],
        )
        assert e["variant"] == ""


class TestCodexReview:
    """Codex 審查找到的（2026-11-21，docs/catalog.md）。"""

    def test_a_listing_with_only_a_height_is_not_a_no_size_listing(self, tmp_path):
        got = offers_for(
            tmp_path,
            [("big", "Ø50", None, None, 267, 500, 1), ("tall", "高 50", None, None, 500, None, 1)],
            [("big", "nosa", 39900, 1, None, SEEN), ("tall", "loft", 30000, 1, None, SEEN)],
        )
        assert [o["store"] for o in got] == ["nosa"], "只標高度的不知道是不是同一個尺寸"

    def test_only_http_links_are_published(self, tmp_path):
        db = make_db(
            tmp_path / "a.db",
            [("w", "白", None, None, 267, 500, 1)],
            [("w", "nosa", 39900, 1, None, SEEN), ("w", "evil", 100, 1, None, SEEN)],
        )
        con = sqlite3.connect(db)
        con.execute("UPDATE listing SET url = 'javascript:alert(1)' WHERE site_id = 'evil'")
        con.commit()
        con.close()
        rows = ex.load_listings([db])["lp__ph-5"]
        assert [o["store"] for o in ex.offers(rows, (50, 26.7))] == ["nosa"]

    def test_the_date_comes_from_the_listed_size_only(self, tmp_path):
        db = make_db(
            tmp_path / "a.db",
            [("big", "Ø50", None, None, 267, 500, 1), ("mini", "Ø30", None, None, 160, 300, 1)],
            [
                ("big", "nosa", 39900, 1, None, "2026-11-19"),
                ("mini", "jyt", 19000, 1, None, "2026-11-21"),
            ],
        )
        outlines = outline_db(tmp_path / "o.db", [("lp__ph-5", "ok", "big", 50, 26.7, LATHE)])
        entry = ex.build([db], outlines, photo_for=lambda url: None)["lamps"][0]
        assert entry["updated"] == "2026-11-19"

    def test_without_a_listed_height_the_photo_estimate_is_given(self, tmp_path):
        db = make_db(
            tmp_path / "a.db",
            [("w", "白", None, None, None, 500, 1)],
            [("w", "nosa", 39900, 1, None, SEEN)],
        )
        outlines = outline_db(tmp_path / "o.db", [("lp__ph-5", "ok", "w", 50, None, LATHE)])
        entry = ex.build([db], outlines, photo_for=lambda url: None)["lamps"][0]
        assert entry["size"] == {"w": 50, "hEst": 26.7}, "高度是照片的比例估的，要講清楚"

    def test_a_lamp_named_wall_lamp_is_left_out_even_if_filed_as_ceiling(self):
        assert batch.wall_name("Clessidra Wall Lamp") and batch.wall_name("Nimal 雙頭壁燈")
        assert not batch.wall_name("Over Me Ceiling/Wall Lamp"), "吸頂、壁掛兩用的可以掛天花板"
        assert not batch.wall_name("PH 5")
