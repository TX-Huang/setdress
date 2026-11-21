"""地毯（rugs.py）：尺寸、各家價格、照片能不能當花紋。驗收句子在 docs/rugs.md。"""

import json
import sqlite3

import numpy as np
import pytest

import rugs

SCHEMA = """
CREATE TABLE brand(brand_id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE site(site_id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE product(product_id TEXT PRIMARY KEY, brand_id INTEGER, model TEXT,
                     cat1 TEXT, cat2 TEXT);
CREATE TABLE variant(variant_id TEXT PRIMARY KEY, product_id TEXT, name TEXT,
                     width_mm REAL, depth_mm REAL, height_mm REAL, diameter_mm REAL, pack INTEGER);
CREATE TABLE listing(listing_id INTEGER PRIMARY KEY, variant_id TEXT, site_id TEXT, url TEXT,
                     price REAL, in_stock INTEGER, gone_at TEXT, last_seen_at TEXT);
CREATE TABLE image(image_id INTEGER PRIMARY KEY, product_id TEXT, variant_id TEXT, src_url TEXT,
                   position INTEGER);
"""
SEEN = "2026-11-21"


def make_db(path, variants, listings, images=(("main", None, 0),), cat=("textile", "rug")):
    """variants: [(id, 名稱, 寬, 深, 直徑)] mm；listings: [(variant, 店, 價格)]

    images: [(網址, variant, 位置)]
    """
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.execute("INSERT INTO brand VALUES (1, 'Muuto')")
    db.execute("INSERT INTO product VALUES ('muuto__varjo', 1, 'Varjo Rug', ?, ?)", cat)
    for vid, name, w, d, dia in variants:
        db.execute(
            "INSERT INTO variant VALUES (?, 'muuto__varjo', ?, ?, ?, NULL, ?, 1)",
            (vid, name, w, d, dia),
        )
    for i, (vid, store, price) in enumerate(listings):
        db.execute("INSERT OR IGNORE INTO site VALUES (?, ?)", (store, store))
        db.execute(
            "INSERT INTO listing(variant_id, site_id, url, price, in_stock, gone_at, last_seen_at)"
            " VALUES (?, ?, ?, ?, 1, NULL, ?)",
            (vid, store, f"https://{store}.example.com/p/{i}", price, SEEN),
        )
    for url, vid, pos in images:
        full = url if url.startswith("http") else f"https://cdn.shopify.com/s/files/{url}.jpg"
        db.execute(
            "INSERT INTO image(product_id, variant_id, src_url, position)"
            " VALUES ('muuto__varjo', ?, ?, ?)",
            (vid, full, pos),
        )
    db.commit()
    db.close()
    return path


# ---------------------------------------------------------------- 尺寸
class TestSizes:
    def test_a_rectangle_is_long_side_by_short_side(self):
        assert rugs.rug_size(2400, 1700, None) == ("rect", 240, 170)
        assert rugs.rug_size(1700, 2400, None) == ("rect", 240, 170), "直的橫的同一個尺寸"

    def test_a_diameter_is_a_round_rug(self):
        assert rugs.rug_size(None, None, 2000) == ("round", 200, 200)

    def test_a_diameter_with_the_same_width_and_depth_is_still_round(self):
        """有的店圓的也寫寬、深（Codex 審查）。"""
        assert rugs.rug_size(2000, 2000, 2000) == ("round", 200, 200)

    def test_no_size_is_none(self):
        assert rugs.rug_size(None, None, None) is None
        assert rugs.rug_size(2400, None, None) is None, "只有一邊不知道形狀"


class TestSizesAndOffers:
    def test_each_size_lists_only_its_own_prices_cheapest_per_store(self, tmp_path):
        make_db(
            tmp_path / "a.db",
            [
                ("s-blue", "170x240 / 藍", 1700, 2400, None),
                ("s-grey", "170x240 / 灰", 1700, 2400, None),
                ("l-blue", "200x300 / 藍", 2000, 3000, None),
            ],
            [
                ("s-blue", "jyt", 32000),
                ("s-grey", "jyt", 30000),
                ("l-blue", "jyt", 52000),
                ("s-blue", "nosa", 33000),
            ],
        )
        sizes = rugs.load(tmp_path / "a.db")["muuto__varjo"]["sizes"]
        assert [(s["shape"], s["w"], s["d"]) for s in sizes] == [
            ("rect", 240, 170),
            ("rect", 300, 200),
        ]
        assert [(o["store"], o["price"]) for o in sizes[0]["offers"]] == [
            ("jyt", 30000),
            ("nosa", 33000),
        ]
        assert [o["price"] for o in sizes[1]["offers"]] == [52000]

    def test_a_size_without_any_price_is_left_out(self, tmp_path):
        make_db(
            tmp_path / "a.db",
            [("a", "170x240", 1700, 2400, None), ("b", "200x300", 2000, 3000, None)],
            [("a", "jyt", 30000)],
        )
        assert [s["w"] for s in rugs.load(tmp_path / "a.db")["muuto__varjo"]["sizes"]] == [240]

    def test_only_rugs(self, tmp_path):
        db = make_db(
            tmp_path / "a.db",
            [("a", "x", 1700, 2400, None)],
            [("a", "jyt", 3000)],
            cat=("decor", "tray"),
        )
        assert rugs.load(db) == {}


# ---------------------------------------------------------------- 照片能不能當花紋
def rug_photo(w=200, h=140, img=(300, 300), shape="rect"):
    """白底，正中間一張有花紋的地毯（w x h px）。"""
    img_h, img_w = img
    out = np.full((img_h, img_w, 3), 255, dtype=np.uint8)
    y0, x0 = (img_h - h) // 2, (img_w - w) // 2
    yy, xx = np.mgrid[:img_h, :img_w]
    if shape == "rect":
        inside = (yy >= y0) & (yy < y0 + h) & (xx >= x0) & (xx < x0 + w)
    elif shape == "slanted":  # 斜著拍：上面窄、下面寬的梯形
        half = (0.35 + 0.15 * (yy - y0) / h) * w
        inside = (yy >= y0) & (yy < y0 + h) & (np.abs(xx + 0.5 - img_w / 2) <= half)
    else:  # 圓的
        inside = ((yy - img_h / 2) / (h / 2)) ** 2 + ((xx - img_w / 2) / (w / 2)) ** 2 <= 1
    stripes = np.where(((xx // 10) % 2) == 0, 60, 180)
    out[inside] = np.stack([stripes, stripes - 20, stripes - 40], axis=-1)[inside]
    return out


class TestLayout:
    def test_a_top_down_rug_gives_its_box_and_outline(self):
        lay = rugs.layout(rug_photo(), ("rect", 240, 170))
        x0, y0, x1, y1 = lay["crop"]
        assert (x0, y0) == pytest.approx((50 / 300, 80 / 300), abs=0.01)
        assert (x1, y1) == pytest.approx((250 / 300, 220 / 300), abs=0.01)
        pts = np.array(lay["outline"])
        assert pts.min() >= -1e-9 and pts.max() <= 1 + 1e-9
        assert len(pts) >= 4
        assert lay["wide"] is True, "照片裡地毯是橫的（長邊左右）"

    def test_a_round_rug_has_a_round_outline(self):
        lay = rugs.layout(rug_photo(160, 160, shape="round"), ("round", 200, 200))
        pts = np.array(lay["outline"])
        r = np.hypot(pts[:, 0] - 0.5, pts[:, 1] - 0.5)
        assert r.min() > 0.4 and r.max() < 0.52, "外形是圓的，不是方的"

    def test_a_rug_touching_the_edge_is_not_used(self):
        assert rugs.layout(rug_photo(300, 140), ("rect", 240, 112)) is None

    def test_proportions_more_than_20_percent_off_are_not_used(self):
        assert rugs.layout(rug_photo(150, 150), ("rect", 240, 170)) is None, (
            "方的照片配長方的尺寸：可能是斜著拍"
        )

    def test_a_rotated_photo_is_fine(self):
        lay = rugs.layout(rug_photo(140, 200), ("rect", 240, 170))
        assert lay is not None and lay["wide"] is False

    def test_a_slanted_photo_is_not_used(self):
        """斜著拍的地毯是梯形：外框的長寬比可能對，但貼上去會歪（Codex 審查）。"""
        assert rugs.layout(rug_photo(w=200, h=140, shape="slanted"), ("rect", 240, 170)) is None

    def test_a_thin_drawing_that_fills_less_than_half_is_not_used(self):
        img = np.full((300, 300, 3), 255, dtype=np.uint8)
        img[80:220, 50:56] = 40
        img[80:86, 50:250] = 40
        img[214:220, 50:250] = 40
        assert rugs.layout(img, ("rect", 240, 170)) is None

    def test_the_colour_is_the_rugs_middle_colour(self):
        img = np.full((300, 300, 3), 255, dtype=np.uint8)
        img[80:220, 50:250] = (120, 90, 60)
        assert rugs.colour(img) == 0x785A3C


class TestHotlink:
    def test_only_photo_servers_that_allow_other_sites(self):
        assert rugs.can_hotlink("https://cdn.shopify.com/s/files/a.jpg")
        assert rugs.can_hotlink("https://img.shoplineapp.com/media/a/original.jpg")
        assert not rugs.can_hotlink("https://www.nordic.com.tw/uploads/a.jpg")
        assert not rugs.can_hotlink("https://www.loft29.com.tw/images/a.jpg")


# ---------------------------------------------------------------- 整份
def save_photo(tmp_path, img):
    from PIL import Image

    path = tmp_path / "rug.png"
    Image.fromarray(img).save(path)
    return path


class TestBuild:
    def test_a_rug_with_a_usable_photo_has_its_link_box_and_outline(self, tmp_path):
        db = make_db(
            tmp_path / "a.db",
            [("s", "170x240 / 藍", 1700, 2400, None)],
            [("s", "jyt", 30000)],
            images=(("main", None, 0), ("blue", "s", 1)),
        )
        photo = save_photo(tmp_path, rug_photo())
        item = rugs.build([db], photo_for=lambda url: photo)["items"][0]
        assert item["id"] == "r:muuto__varjo" and item["category"] == "地毯"
        assert item["photo"]["url"] == "https://cdn.shopify.com/s/files/blue.jpg?width=1000", (
            "款式自己的照片、要小張的"
        )
        assert len(item["photo"]["crop"]) == 4 and len(item["photo"]["outline"]) >= 4
        assert item["variant"] == "170x240 / 藍"

    def test_a_photo_from_a_server_that_blocks_other_sites_is_colour_only(self, tmp_path):
        db = make_db(
            tmp_path / "a.db",
            [("s", "170x240", 1700, 2400, None)],
            [("s", "jyt", 30000)],
            images=(("https://www.loft29.com.tw/images/a.jpg", None, 0),),
        )
        photo = save_photo(tmp_path, rug_photo())
        item = rugs.build([db], photo_for=lambda url: photo)["items"][0]
        assert item["photo"] is None
        assert [s["photoFits"] for s in item["sizes"]] == [False]
        assert item["colour"] != rugs.GREY, "還是可以從照片量顏色"

    def test_without_a_downloaded_photo_the_colour_is_neutral_grey(self, tmp_path):
        db = make_db(tmp_path / "a.db", [("s", "170x240", 1700, 2400, None)], [("s", "jyt", 30000)])
        item = rugs.build([db], photo_for=lambda url: None)["items"][0]
        assert (item["photo"], item["colour"]) == (None, rugs.GREY)

    def test_the_file_is_the_same_every_time_and_has_no_local_paths(self, tmp_path):
        db = make_db(tmp_path / "a.db", [("s", "170x240", 1700, 2400, None)], [("s", "jyt", 30000)])
        photo = save_photo(tmp_path, rug_photo())
        data = rugs.build([db], photo_for=lambda url: photo)
        a, b = tmp_path / "a.js", tmp_path / "b.js"
        rugs.write(data, a)
        rugs.write(json.loads(json.dumps(data)), b)
        assert a.read_bytes() == b.read_bytes()
        text = a.read_text(encoding="utf-8")
        assert "root.SetdressRugs = data" in text
        assert str(tmp_path) not in text and "out/photos" not in text, "本機的照片路徑不放進網站"


def photo_fits(tmp_path, photo_img, variants):
    """每個尺寸 → 照片能不能用在它身上。variants: [(id, 寬, 深, 直徑)] mm"""
    data = built(tmp_path, photo_img, variants)
    return {(s["shape"], s["w"], s["d"]): s["photoFits"] for s in data["items"][0]["sizes"]}


def built(tmp_path, photo_img, variants):
    """一件商品、這些尺寸、這張照片 → 整份資料（也確定寫得出 rugs.js）。"""
    db = make_db(
        tmp_path / "a.db",
        [(vid, vid, w, d, dia) for vid, w, d, dia in variants],
        [(vid, "jyt", 30000 + i) for i, (vid, *_) in enumerate(variants)],
    )
    photo = save_photo(tmp_path, photo_img)
    data = rugs.build([db], photo_for=lambda url: photo)
    rugs.write(data, tmp_path / "rugs.js")  # 寫得出來（numpy 的 True/False 寫不進 JSON）
    return data


class TestPhotoFitsEachSize:
    def test_only_sizes_with_the_photos_proportions(self, tmp_path):
        fits = photo_fits(
            tmp_path,
            rug_photo(),  # 橫的 200:140
            [("a", 1700, 2400, None), ("b", 2500, 2500, None), ("c", 2000, 3000, None)],
        )
        assert fits == {
            ("rect", 240, 170): True,
            ("rect", 250, 250): False,
            ("rect", 300, 200): True,
        }

    def test_a_round_photo_fits_the_round_size_not_the_square_one(self, tmp_path):
        fits = photo_fits(
            tmp_path,
            rug_photo(w=200, h=200, shape="round"),
            [("sq", 2000, 2000, None), ("ro", None, None, 2000)],
        )
        assert fits == {("rect", 200, 200): False, ("round", 200, 200): True}

    def test_a_square_photo_fits_the_square_size_not_the_round_one(self, tmp_path):
        fits = photo_fits(
            tmp_path,
            rug_photo(w=200, h=200),
            [("sq", 2000, 2000, None), ("ro", None, None, 2000), ("long", 2000, 3000, None)],
        )
        assert fits == {
            ("rect", 200, 200): True,
            ("round", 200, 200): False,
            ("rect", 300, 200): False,  # 一樣是方的，但長寬比不對
        }

    def test_an_oval_photo_still_fits_sizes_given_as_width_by_length(self, tmp_path):
        """橢圓、不規則的地毯常常標「寬 x 長」：沒有圓的尺寸可以選，就不用猜圓方。"""
        fits = photo_fits(
            tmp_path, rug_photo(w=200, h=140, shape="round"), [("a", 1700, 2400, None)]
        )
        assert fits == {("rect", 240, 170): True}

    def test_a_square_photo_does_not_fit_a_round_only_rug(self, tmp_path):
        """只有圓的尺寸、照片卻是方的：不貼（Codex 審查）。"""
        (item,) = built(tmp_path, rug_photo(w=200, h=200), [("ro", None, None, 2000)])["items"]
        assert [s["photoFits"] for s in item["sizes"]] == [False]
        assert item["photo"] is None, "一個尺寸都不能用，就當沒有照片花紋"

    def test_without_a_usable_photo_no_size_fits(self, tmp_path):
        fits = photo_fits(tmp_path, rug_photo(w=280, h=60), [("a", 1700, 2400, None)])
        assert fits == {("rect", 240, 170): False}


class TestWhatCounts:
    def test_packs_and_delisted_listings_are_not_counted(self, tmp_path):
        db = make_db(
            tmp_path / "a.db",
            [("a", "一張", 1700, 2400, None), ("b", "兩張一組", 1700, 2400, None)],
            [("a", "jyt", 30000), ("a", "nosa", 20000), ("b", "wow", 10000)],
        )
        con = sqlite3.connect(db)
        con.execute("UPDATE variant SET pack = 2 WHERE variant_id = 'b'")
        con.execute("UPDATE listing SET gone_at = '2026-11-20' WHERE site_id = 'nosa'")
        con.commit()
        con.close()
        (item,) = rugs.load(db).values()
        assert [o["store"] for o in item["sizes"][0]["offers"]] == ["jyt"]

    def test_the_same_rug_in_two_databases_keeps_both_stores(self, tmp_path):
        """--db 給好幾個：同一件商品在兩個資料庫，兩邊的價格都留（Codex 審查）。"""
        (tmp_path / "x").mkdir()
        (tmp_path / "y").mkdir()
        a = make_db(tmp_path / "x" / "a.db", [("a", "", 1700, 2400, None)], [("a", "jyt", 30000)])
        b = make_db(tmp_path / "y" / "b.db", [("a", "", 1700, 2400, None)], [("a", "wow", 28000)])
        (item,) = rugs.build([a, b], photo_for=lambda url: None)["items"]
        assert [o["store"] for o in item["sizes"][0]["offers"]] == ["wow", "jyt"]
