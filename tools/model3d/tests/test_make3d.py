"""批次生 3D（make3d.py）：順序、選照片、存檔、跳過。用假的 AI（不用顯示卡）。

驗收句子在 docs/model3d.md 第 1 到 6 句。
"""

import json

import numpy as np
from test_shape import box

import make3d


def item(pid, offers=1, photos=("a", "b"), mount="floor"):
    size = {
        "w": 200, "d": 90, "h": 80, "mount": mount,
        "photos": [f"https://cdn.shopify.com/{p}.jpg" for p in photos],
        "offers": [{"store": f"s{i}", "price": 100} for i in range(offers)],
    }  # fmt: skip
    return {"id": f"g:{pid}", "brand": "B", "name": pid, "sizes": [size]}


def photo_with_box():
    """白底、中間一塊（40 x 20），像一張單色背景的商品照。"""
    rgb = np.full((60, 80, 3), 255, dtype=np.uint8)
    rgb[20:40, 20:60] = (90, 90, 90)
    return rgb


class FakeAI:
    """假的 AI：回一個方塊，寬:高 = 2:1（跟照片裡的商品一樣），記下拿到的照片。"""

    def __init__(self):
        self.inputs = []

    def __call__(self, image):
        self.inputs.append(image)
        return box(-1.0, -0.5, -0.4, 1.0, 0.5, 0.4)


def cut_ok(rgb, allow_top):
    alpha = np.zeros(rgb.shape[:2], dtype=np.uint8)
    alpha[20:40, 20:60] = 255
    return {"ok": True, "box": [20, 20, 60, 40]}, alpha


def cut_scene(rgb, allow_top):
    return {"ok": False, "reason": "scene", "box": None}, None


class TestOrder:
    def test_stores_carrying_it_first_and_kinds_take_turns(self):
        groups = {
            "sofa": [item("s1", offers=1), item("s2", offers=3)],
            "chair": [item("c1", offers=2)],
        }
        assert [i["id"] for i in make3d.order(groups)] == ["g:s2", "g:c1", "g:s1"]


class TestChoosePhoto:
    def test_first_photo_that_can_be_cut_out(self):
        seen = []

        def fetch(url):
            seen.append(url)
            return photo_with_box()

        def cut(rgb, allow_top):
            return (cut_scene if len(seen) == 1 else cut_ok)(rgb, allow_top)

        url, _, alpha, box_px, k = make3d.choose_photo(item("x"), fetch, cut)
        assert url.endswith("/b.jpg") and box_px == [20, 20, 60, 40]
        assert k == 1, "第幾張照片（網頁用來確認同一款）"
        assert alpha.shape == (60, 80)

    def test_says_why_when_no_photo_works(self):
        """照片都讀得到但都不能去背：不適合（不再試）；讀不到：可能只是網路斷了（下次再試）。"""
        assert make3d.choose_photo(item("x"), lambda url: photo_with_box(), cut_scene) == "photo"
        assert make3d.choose_photo(item("x"), lambda url: None, cut_ok) == "fetch"

    def test_pendant_lamps_may_touch_the_top(self):
        got = []
        make3d.choose_photo(item("x", mount="ceiling"), lambda url: photo_with_box(),
                            lambda rgb, top: got.append(top) or cut_ok(rgb, top))  # fmt: skip
        assert got == [True]


class TestMakeOne:
    def test_writes_a_model_facing_the_camera_on_the_floor_with_photo_coordinates(self):
        ai = FakeAI()
        glb_bytes, meta = make3d.make_one(item("x"), ai, lambda url: photo_with_box(), cut_ok)
        assert glb_bytes[:4] == b"glTF"
        assert meta["photo"].endswith("/a.jpg") and meta["box"] == [20, 20, 60, 40]
        assert meta["photoIndex"] == 0
        assert meta["wh"] == [80, 60]
        np.testing.assert_allclose(meta["extent"], [2.0, 1.0, 0.8], atol=1e-5)
        assert meta["score"] > 0.9
        assert ai.inputs[0].shape == (48, 48, 3), "給 AI 的是正方形、四周留一成"

    def test_a_shape_that_does_not_match_the_photo_is_not_used(self):
        def tall_ai(image):
            return box(-0.2, -1.0, -0.2, 0.2, 1.0, 0.2)  # 細長的，照片是扁的

        glb_bytes, meta = make3d.make_one(item("x"), tall_ai, lambda url: photo_with_box(), cut_ok)
        assert glb_bytes is None and meta["skip"] == "shape"

    def test_no_usable_photo_is_skipped(self):
        glb_bytes, meta = make3d.make_one(
            item("x"), FakeAI(), lambda url: photo_with_box(), cut_scene
        )
        assert glb_bytes is None and meta == {"skip": "photo"}


class TestRun:
    def test_saves_each_model_and_the_index_and_skips_ones_done_before(self, tmp_path):
        ai = FakeAI()
        items = [item("a"), item("b")]
        kw = {
            "fetch": lambda url: photo_with_box(),
            "cut": cut_ok,
            "out": tmp_path,
            "skipped": tmp_path / "s.json",
        }
        make3d.run(items, ai, **kw)
        index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
        assert set(index["models"]) == {"g:a", "g:b"}
        files = [index["models"][k]["file"] for k in ("g:a", "g:b")]
        assert all((tmp_path / f).read_bytes()[:4] == b"glTF" for f in files)
        assert len(set(files)) == 2 and all(f.endswith(".glb") and ":" not in f for f in files)
        make3d.run(items, ai, **kw)
        assert len(ai.inputs) == 2, "做過的不再做"

    def test_a_photo_that_could_not_be_downloaded_is_tried_again_next_time(self, tmp_path):
        """一次讀不到可能只是網路斷了：不記成「跳過」（Codex 審查）。"""
        kw = {"cut": cut_ok, "out": tmp_path / "site", "skipped": tmp_path / "s.json"}
        make3d.run([item("a")], FakeAI(), fetch=lambda url: None, **kw)
        assert make3d.load_skipped(tmp_path / "s.json") == {}
        ai = FakeAI()
        make3d.run([item("a")], ai, fetch=lambda url: photo_with_box(), **kw)
        assert len(ai.inputs) == 1

    def test_redo_when_the_goods_photos_changed(self, tmp_path):
        """重新爬過、照片換了：舊的 3D 的照片不在了，重做；跳過的也重試（Codex 審查）。"""
        kw = {
            "fetch": lambda url: photo_with_box(),
            "out": tmp_path,
            "skipped": tmp_path / "s.json",
        }
        make3d.run([item("a"), item("b")], FakeAI(), cut=lambda rgb, top: cut_ok(rgb, top), **kw)
        make3d.run([item("c")], FakeAI(), cut=cut_scene, **kw)
        ai = FakeAI()
        make3d.run(
            [item("a"), item("b", photos=("new",)), item("c", photos=("new",))],
            ai,
            cut=cut_ok,
            **kw,
        )
        assert len(ai.inputs) == 2, "b 的照片換了、c 的照片換了；a 沒變不重做"

    def test_skipped_ones_are_remembered_outside_the_site(self, tmp_path):
        ai = FakeAI()
        site, skipped = tmp_path / "site", tmp_path / "local" / "skipped.json"
        make3d.run(
            [item("a")],
            ai,
            fetch=lambda url: photo_with_box(),
            cut=cut_scene,
            out=site,
            skipped=skipped,
        )
        index = json.loads((site / "index.json").read_text(encoding="utf-8"))
        assert index["models"] == {}
        assert make3d.load_skipped(skipped)["g:a"]["reason"] == "photo"
        assert make3d.SKIPPED.parent.name == "out", "預設放在 tools/model3d/out（不上網站）"
        kw = {"fetch": lambda url: photo_with_box(), "cut": cut_ok, "out": site, "skipped": skipped}
        make3d.run([item("a")], ai, **kw)
        assert ai.inputs == [], "跳過的也不再試（要重試就刪掉 skipped.json）"

    def test_limit_counts_every_new_try_not_only_successes(self, tmp_path):
        """--limit 50 遇到一堆不能用的照片，也不會一路試幾千件（Codex 審查）。"""
        tries = []

        def cut(rgb, top):
            tries.append(1)
            return cut_scene(rgb, top) if len(tries) == 1 else cut_ok(rgb, top)

        kw = {
            "fetch": lambda url: photo_with_box(),
            "out": tmp_path,
            "skipped": tmp_path / "s.json",
        }
        make3d.run(
            [item("a", photos=("x",)), item("b"), item("c")], FakeAI(), cut=cut, limit=2, **kw
        )
        models = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))["models"]
        assert list(models) == ["g:b"], "試了 a（不行）和 b，就停"

    def test_files_are_written_whole(self, tmp_path):
        """存檔先寫到暫存檔再換過去：中途停掉不會留下壞掉的 JSON（Codex 審查）。"""
        kw = {
            "fetch": lambda url: photo_with_box(),
            "cut": cut_ok,
            "out": tmp_path,
            "skipped": tmp_path / "s.json",
        }
        make3d.run([item("a")], FakeAI(), **kw)
        assert sorted(p.name for p in tmp_path.iterdir() if p.suffix != ".glb") == ["index.json"]
