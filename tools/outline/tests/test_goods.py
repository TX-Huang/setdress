"""全部商品（goods.py）：分類、放法、尺寸、價格、照片。驗收句子在 docs/goods.md。"""

import json
import sqlite3

import pytest
from test_rugs import SCHEMA, SEEN

import goods


class Shop:
    """測試用的小資料庫：一次加一件商品。"""

    def __init__(self, path):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT INTO brand VALUES (1, 'Muuto')")
        self.n = 0

    def add(self, pid, model, cat, variants, listings, images=()):
        """variants: [(id, 名稱, 寬, 深, 高, 直徑)] mm；listings: [(variant, 店, 價格)]

        images: [(網址, variant)]，照順序
        """
        self.db.execute("INSERT INTO product VALUES (?, 1, ?, ?, ?)", (pid, model, *cat))
        for vid, name, w, d, h, dia in variants:
            self.db.execute(
                "INSERT INTO variant VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (vid, pid, name, w, d, h, dia),
            )
        for vid, store, price in listings:
            self.n += 1
            self.db.execute("INSERT OR IGNORE INTO site VALUES (?, ?)", (store, store))
            self.db.execute(
                "INSERT INTO listing(variant_id, site_id, url, price, in_stock, gone_at,"
                " last_seen_at) VALUES (?, ?, ?, ?, 1, NULL, ?)",
                (vid, store, f"https://{store}.example.com/p/{self.n}", price, SEEN),
            )
        for pos, (url, vid) in enumerate(images):
            self.db.execute(
                "INSERT INTO image(product_id, variant_id, src_url, position) VALUES (?, ?, ?, ?)",
                (pid, vid, f"https://cdn.shopify.com/s/files/{url}.jpg", pos),
            )
        return self

    def done(self):
        self.db.commit()
        self.db.close()
        return self.path


SOFA = ("furniture", "sofa")


class TestGroups:
    @pytest.mark.parametrize(
        ("cat", "name", "group"),
        [
            (("furniture", "sofa"), "Rest", "sofa"),
            (("lighting", "pendant"), "PH 5", "lamp-pendant"),
            (("decor", "mirror"), "Oval", "mirror"),
            (("art", "print"), "Poster", "art"),
            (("decor", None), "Bowl", "decor"),
        ],
    )
    def test_by_the_crawlers_category(self, cat, name, group):
        assert goods.group_of(*cat, name) == group

    def test_rugs_have_their_own_card(self):
        assert goods.group_of("textile", "rug", "Varjo") is None

    @pytest.mark.parametrize(
        ("name", "group"),
        [
            ("Ena 三人沙發", "sofa"),
            ("Sweep 吊燈", "lamp-pendant"),
            ("PINOKIO Table 桌鏡", "mirror"),  # 不是桌子
            ("Akari 桌燈", "lamp-table"),  # 不是桌子
            ("Ena Office Drawer 活動櫃", "storage"),
            ("Birdy Table Lamp 柏蒂系列 懸臂", "lamp-table"),  # 英文的桌燈
            ("Aluminium Sofa Table 鋁合金", "table"),  # 沙發邊桌是桌子
            ("Krenit 沙拉碗 / 杓匙組", "other"),
        ],
    )
    def test_uncategorised_ones_by_their_name(self, name, group):
        assert goods.group_of("unknown", None, name) == group

    @pytest.mark.parametrize(
        ("cat", "name", "group"),
        [
            (("furniture", None), "Ena 三人沙發", "sofa"),
            (("lighting", None), "Sweep 吊燈", "lamp-pendant"),
            (("decor", None), "MOVV 時鐘", "clock"),
            (("furniture", None), "Screen 屏風", "furniture"),
            (("decor", None), "Bowl", "decor"),
        ],
    )
    def test_a_vague_category_looks_at_the_name_first(self, cat, name, group):
        """爬到的分類只寫「家具」「燈」「擺飾」：名稱看得出來就照名稱分（Codex 審查）。"""
        assert goods.group_of(*cat, name) == group

    def test_every_group_has_a_label_mount_and_ordinary_size(self):
        for g in goods.GROUPS.values():
            assert g.label and g.mount in {"floor", "table", "wall", "ceiling"}
            assert all(v > 0 for v in g.size)


class TestMount:
    def test_by_group(self):
        assert goods.mount_of("sofa", {"h": 80}) == "floor"
        assert goods.mount_of("lamp-pendant", {"h": 30}) == "ceiling"
        assert goods.mount_of("art", {"h": 70}) == "wall"
        assert goods.mount_of("vase", {"h": 30}) == "table"

    def test_tall_decor_goes_on_the_floor(self):
        assert goods.mount_of("vase", {"h": 90}) == "floor"
        assert goods.mount_of("planter", {"h": 70}) == "floor"

    def test_a_tall_mirror_leans_on_the_floor(self):
        assert goods.mount_of("mirror", {"h": 160}) == "floor"
        assert goods.mount_of("mirror", {"h": 80}) == "wall"

    def test_a_mirror_called_a_wall_mirror_stays_on_the_wall(self):
        assert goods.mount_of("mirror", {"h": 211}, "Nimbus 壁鏡") == "wall"
        assert goods.mount_of("mirror", {"h": 211}, "Wall Mirror XL") == "wall"


def one(tmp_path, variants, listings, images=(("main", None),), cat=SOFA, name="Rest"):
    path = Shop(tmp_path / "a.db").add("muuto__rest", name, cat, variants, listings, images).done()
    return goods.load(path)["muuto__rest"]


class TestSizesAndOffers:
    def test_each_size_has_its_own_prices_cheapest_per_store(self, tmp_path):
        item = one(
            tmp_path,
            [("a", "小", 1800, 900, 800, None), ("b", "大", 2400, 950, 800, None)],
            [("a", "jyt", 50000), ("a", "jyt", 48000), ("a", "wow", 52000), ("b", "wow", 70000)],
        )
        assert [(s["w"], s["d"], s["h"]) for s in item["sizes"]] == [(180, 90, 80), (240, 95, 80)]
        assert [(o["store"], o["price"]) for o in item["sizes"][0]["offers"]] == [
            ("jyt", 48000),
            ("wow", 52000),
        ]
        assert [o["store"] for o in item["sizes"][1]["offers"]] == ["wow"]
        assert not any(s.get("guess") for s in item["sizes"])

    def test_a_diameter_is_the_width_and_depth(self, tmp_path):
        item = one(
            tmp_path,
            [("a", "", None, None, 750, 900)],
            [("a", "jyt", 30000)],
            cat=("furniture", "table"),
        )
        assert [(s["w"], s["d"], s["h"]) for s in item["sizes"]] == [(90, 90, 75)]

    def test_without_any_size_uses_the_ordinary_size_and_says_so(self, tmp_path):
        item = one(tmp_path, [("a", "", None, None, None, None)], [("a", "jyt", 30000)])
        (size,) = item["sizes"]
        assert (size["w"], size["d"], size["h"]) == goods.GROUPS["sofa"].size
        assert size["guess"] is True
        assert [o["price"] for o in size["offers"]] == [30000]
        assert size["seen"] == SEEN, "更新日期還是要有（Codex 審查）"

    def test_sides_filled_in_from_the_ordinary_size_are_marked(self, tmp_path):
        """只標寬：深、高照一般比例補，標成「估的」（網頁不拿來算大小）。"""
        item = one(tmp_path, [("a", "", 900, None, None, None)], [("a", "jyt", 30000)])
        (size,) = item["sizes"]
        assert size["est"] == ["d", "h"]
        (tmp_path / "x").mkdir()
        full = one(tmp_path / "x", [("a", "", 1800, 900, 800, None)], [("a", "jyt", 1)])
        assert "est" not in full["sizes"][0]

    def test_a_missing_side_never_rounds_to_zero(self, tmp_path):
        item = one(
            tmp_path,
            [("a", "", 6, None, 55, None)],
            [("a", "jyt", 420)],
            cat=("decor", "wall_decor"),
        )
        assert all(item["sizes"][0][k] > 0 for k in "wdh")

    def test_furniture_with_an_impossibly_small_size_uses_the_ordinary_size(self, tmp_path):
        """爬到的尺寸偶爾單位錯（沙發寬 0.8 cm）：家具最長的邊不到一般的兩成，當成沒標。"""
        item = one(tmp_path, [("a", "", 8, 5, 7, None)], [("a", "jyt", 30000)])
        (size,) = item["sizes"]
        assert (size["w"], size["d"], size["h"]) == goods.GROUPS["sofa"].size
        assert size["guess"] is True

    def test_furniture_with_one_impossible_side_uses_the_ordinary_size(self, tmp_path):
        """寬 0.8 cm、高 80 cm 的沙發：最長的邊看起來對，但寬不可能（Codex 審查）。"""
        item = one(tmp_path, [("a", "", 8, 5, 800, None)], [("a", "jyt", 30000)])
        assert item["sizes"][0]["guess"] is True

    def test_furniture_far_too_big_uses_the_ordinary_size(self, tmp_path):
        item = one(tmp_path, [("a", "", 20000, 900, 800, None)], [("a", "jyt", 30000)])
        assert item["sizes"][0]["guess"] is True

    def test_only_one_size_known_counts_the_unsized_variants_too(self, tmp_path):
        item = one(
            tmp_path,
            [("a", "灰", 1800, 900, 800, None), ("b", "藍", None, None, None, None)],
            [("a", "jyt", 50000), ("b", "wow", 45000)],
        )
        assert [o["store"] for o in item["sizes"][0]["offers"]] == ["wow", "jyt"]

    def test_with_several_sizes_an_unsized_variant_counts_for_none_of_them(self, tmp_path):
        item = one(
            tmp_path,
            [
                ("a", "小", 1800, 900, 800, None),
                ("b", "大", 2400, 900, 800, None),
                ("c", "布料", None, None, None, None),
            ],
            [("a", "jyt", 50000), ("b", "jyt", 70000), ("c", "wow", 1000)],
        )
        assert [[o["store"] for o in s["offers"]] for s in item["sizes"]] == [["jyt"], ["jyt"]]

    def test_sizes_of_unpriced_variants_do_not_hide_the_priced_one(self, tmp_path):
        """兩個有尺寸但沒價格的款式、一個沒尺寸但有價格的：整件不能消失（Codex 審查）。"""
        item = one(
            tmp_path,
            [
                ("a", "小", 1800, 900, 800, None),
                ("b", "大", 2400, 900, 800, None),
                ("c", "", None, None, None, None),
            ],
            [("c", "wow", 45000)],
        )
        (size,) = item["sizes"]
        assert size["guess"] is True and [o["store"] for o in size["offers"]] == ["wow"]

    def test_packs_delisted_and_unpriced_are_left_out(self, tmp_path):
        path = (
            Shop(tmp_path / "a.db")
            .add(
                "muuto__rest",
                "Rest",
                SOFA,
                [("a", "", 1800, 900, 800, None), ("b", "兩張", 1800, 900, 800, None)],
                [("a", "jyt", 50000), ("a", "nosa", 40000), ("a", "wow", 0), ("b", "moon", 30000)],
            )
            .done()
        )
        con = sqlite3.connect(path)
        con.execute("UPDATE variant SET pack = 2 WHERE variant_id = 'b'")
        con.execute("UPDATE listing SET gone_at = '2026-11-20' WHERE site_id = 'nosa'")
        con.commit()
        con.close()
        item = goods.load(path)["muuto__rest"]
        assert [o["store"] for o in item["sizes"][0]["offers"]] == ["jyt"]

    def test_a_product_without_any_price_is_left_out(self, tmp_path):
        path = Shop(tmp_path / "a.db").add("x__y", "Y", SOFA, [("a", "", 1, 1, 1, None)], []).done()
        assert goods.load(path) == {}


class TestEachSize:
    def test_each_size_has_its_own_variants_photos_first(self, tmp_path):
        """小的紅椅子、大的藍椅子：選大的要看到藍的（Codex 審查）。"""
        item = one(
            tmp_path,
            [("a", "紅", 500, 500, 800, None), ("b", "藍", 600, 600, 900, None)],
            [("a", "jyt", 9000), ("b", "jyt", 12000)],
            images=[("p1", None), ("red", "a"), ("blue", "b")],
        )
        small, big = item["sizes"]
        assert small["photos"][0].endswith("red.jpg") and big["photos"][0].endswith("blue.jpg")
        assert "p1" in " ".join(big["photos"]), "後面接商品的照片"

    def test_each_size_has_its_own_mount(self, tmp_path):
        """80 cm 的鏡子掛牆、160 cm 的靠地上（Codex 審查）。"""
        item = one(
            tmp_path,
            [("a", "", 600, 30, 800, None), ("b", "", 600, 30, 1600, None)],
            [("a", "jyt", 9000), ("b", "jyt", 12000)],
            cat=("decor", "mirror"),
        )
        assert [s["mount"] for s in item["sizes"]] == ["wall", "floor"]
        assert item["mount"] == "wall", "一開始用第一個尺寸的"


class TestPhotos:
    def test_sized_variants_own_photos_first_then_the_products_no_repeats_at_most_4(self, tmp_path):
        item = one(
            tmp_path,
            [("a", "灰", 1800, 900, 800, None), ("b", "藍", None, None, None, None)],
            [("a", "jyt", 50000)],
            images=[
                ("p1", None),
                ("b1", "b"),
                ("a1", "a"),
                ("p1", None),
                ("p2", None),
                ("p3", None),
            ],
        )
        assert item["sizes"][0]["photos"] == [
            "https://cdn.shopify.com/s/files/a1.jpg",
            "https://cdn.shopify.com/s/files/p1.jpg",
            "https://cdn.shopify.com/s/files/b1.jpg",
            "https://cdn.shopify.com/s/files/p2.jpg",
        ]

    def test_no_photo_is_an_empty_list(self, tmp_path):
        assert (
            one(tmp_path, [("a", "", 1800, 900, 800, None)], [("a", "jyt", 1)], images=())["sizes"][
                0
            ]["photos"]
            == []
        )


class TestBuild:
    def make(self, tmp_path):
        shop = Shop(tmp_path / "a.db")
        shop.add(
            "a__sofa",
            "Rest",
            SOFA,
            [("s", "", 1800, 900, 800, None)],
            [("s", "jyt", 50000)],
            [("s1", None)],
        )
        shop.add("b__sofa", "Alpha", SOFA, [("t", "", 2000, 900, 800, None)], [("t", "wow", 60000)])
        shop.add(
            "c__vase",
            "Tall",
            ("decor", "vase"),
            [("u", "", 300, 300, 900, None)],
            [("u", "jyt", 9000)],
        )
        shop.add(
            "d__rug",
            "Varjo",
            ("textile", "rug"),
            [("r", "", 2400, 1700, None, None)],
            [("r", "jyt", 9000)],
        )
        shop.add(
            "e__x",
            "Krenit 沙拉碗",
            ("unknown", None),
            [("x", "", None, None, None, None)],
            [("x", "a", 900)],
        )
        return shop.done()

    def test_one_file_per_group_and_an_index(self, tmp_path):
        out = tmp_path / "goods"
        goods.write(goods.build([self.make(tmp_path)]), out)
        index = json.loads((out / "index.json").read_text(encoding="utf-8"))
        counts = {g["key"]: g["count"] for g in index["groups"]}
        assert counts == {"sofa": 2, "vase": 1, "other": 1}, "地毯不放；沒有東西的類不列"
        first = index["groups"][0]["label"]
        assert first == goods.GROUPS["sofa"].label, "照固定的順序"
        sofas = json.loads((out / "sofa.json").read_text(encoding="utf-8"))["items"]
        assert [i["name"] for i in sofas] == ["Alpha", "Rest"], "照品牌、型號排"
        assert sofas[0]["id"] == "g:b__sofa" and sofas[0]["mount"] == "floor"
        (vase,) = json.loads((out / "vase.json").read_text(encoding="utf-8"))["items"]
        assert vase["mount"] == "floor", "90 cm 的花瓶放地上"

    def test_the_files_are_the_same_every_time_and_have_no_local_paths(self, tmp_path):
        db = self.make(tmp_path)
        a, b = tmp_path / "a", tmp_path / "b"
        goods.write(goods.build([db]), a)
        goods.write(goods.build([db]), b)
        for f in a.iterdir():
            assert f.read_bytes() == (b / f.name).read_bytes()
            assert str(tmp_path) not in f.read_text(encoding="utf-8")

    def test_old_group_files_are_removed(self, tmp_path):
        out = tmp_path / "goods"
        out.mkdir()
        (out / "gone.json").write_text("{}", encoding="utf-8")
        goods.write(goods.build([self.make(tmp_path)]), out)
        assert not (out / "gone.json").exists()
