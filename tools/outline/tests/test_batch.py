"""批次自動描（batch.py）：挑商品、描、存結果（docs/outline.md「批次」的驗收句子）。

資料庫用最小的假資料庫（只有用到的欄位），照片用畫出來的形狀，下載換成假的。
"""

import json
import sqlite3
from collections import Counter

import numpy as np
import pytest
from PIL import Image

import batch
import outline as ol
import photos

SCHEMA = """
CREATE TABLE product(product_id TEXT PRIMARY KEY, cat1 TEXT, cat2 TEXT, model TEXT);
CREATE TABLE variant(variant_id INTEGER PRIMARY KEY, product_id TEXT,
                     width_mm REAL, depth_mm REAL, height_mm REAL, diameter_mm REAL);
CREATE TABLE image(image_id INTEGER PRIMARY KEY, product_id TEXT, src_url TEXT, position INTEGER);
"""


def make_db(path, products, cat1="lighting"):
    """products: [(product_id, cat2, [(寬, 深, 高, 直徑) mm, ...], {位置: 照片網址})]"""
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    for pid, cat2, sizes, images in products:
        db.execute("INSERT INTO product VALUES (?, ?, ?, ?)", (pid, cat1, cat2, pid))
        for w, d, h, dia in sizes:
            db.execute(
                "INSERT INTO variant(product_id, width_mm, depth_mm, height_mm, diameter_mm)"
                " VALUES (?, ?, ?, ?, ?)",
                (pid, w, d, h, dia),
            )
        for pos, url in images.items():
            db.execute(
                "INSERT INTO image(product_id, src_url, position) VALUES (?, ?, ?)", (pid, url, pos)
            )
    db.commit()
    db.close()
    return path


ROUND = [(None, None, 300, 200)]  # 直徑 20 cm、高 30 cm


def ids(cands):
    return sorted(c.product_id for c in cands)


class TestCandidates:
    def test_only_pendant_table_floor_and_ceiling_lamps(self, tmp_path):
        kinds = ["pendant", "table", "floor", "ceiling", "wall", "bulb", "outdoor", None]
        db = make_db(tmp_path / "a.db", [(f"p-{k}", k, ROUND, {0: "u"}) for k in kinds])
        make_db(tmp_path / "f.db", [("chair", "table", ROUND, {0: "u"})], cat1="furniture")
        cands = batch.candidates([db, tmp_path / "f.db"])
        assert ids(cands) == ["p-ceiling", "p-floor", "p-pendant", "p-table"]

    def test_diameter_or_equal_width_and_depth_is_a_round_size(self, tmp_path):
        db = make_db(
            tmp_path / "a.db",
            [
                ("dia", "pendant", [(None, None, 300, 200)], {0: "u"}),
                ("square", "table", [(200, 210, 300, None)], {0: "u"}),  # 差 5%：算圓的
                ("width-only", "floor", [(250, None, 1500, None)], {0: "u"}),
            ],
        )
        sizes = {c.product_id: c.sizes for c in batch.candidates([db])}
        assert [(s.width_cm, s.height_cm) for s in sizes["dia"]] == [(20, 30)]
        assert [(s.width_cm, s.height_cm) for s in sizes["square"]] == [(20, 30)]
        assert [(s.width_cm, s.height_cm) for s in sizes["width-only"]] == [(25, 150)]

    def test_width_and_depth_more_than_10_percent_apart_is_not_round(self, tmp_path):
        db = make_db(
            tmp_path / "a.db",
            [
                ("long", "table", [(300, 150, 400, None)], {0: "u"}),
                ("mixed", "table", [(300, 150, 400, None), (None, None, 300, 200)], {0: "u"}),
            ],
        )
        cands = {c.product_id: c for c in batch.candidates([db])}
        assert cands["long"].skip == batch.NO_ROUND_SIZE and cands["long"].sizes == []
        assert [s.width_cm for s in cands["mixed"].sizes] == [20], "圓的那個尺寸還是能用"

    def test_no_size_or_no_photo_is_skipped(self, tmp_path):
        db = make_db(
            tmp_path / "a.db",
            [
                ("no-size", "pendant", [(None, None, 300, None)], {0: "u"}),
                ("no-photo", "pendant", ROUND, {}),
            ],
        )
        cands = {c.product_id: c for c in batch.candidates([db])}
        assert cands["no-size"].skip == batch.NO_ROUND_SIZE
        assert cands["no-photo"].skip == batch.NO_PHOTO

    def test_the_first_photo_is_used(self, tmp_path):
        db = make_db(
            tmp_path / "a.db", [("p", "pendant", ROUND, {2: "third", 0: "first", 1: "second"})]
        )
        assert batch.candidates([db])[0].image_url == "first"

    def test_a_product_in_two_databases_is_traced_once(self, tmp_path):
        a = make_db(tmp_path / "a.db", [("same", "pendant", ROUND, {0: "from-a"})])
        b = make_db(tmp_path / "b.db", [("same", "pendant", ROUND, {0: "from-b"})])
        cands = batch.candidates([a, b])
        assert [(c.product_id, c.image_url) for c in cands] == [("same", "from-a")]


class TestPickSize:
    def test_the_size_closest_to_the_photo_proportions_wins(self):
        small, big = batch.Size(1, 20, 30), batch.Size(2, 40, 40)  # 高/寬 1.5 和 1.0
        size, error = batch.pick_size([small, big], photo_ratio=1.05)
        assert size == big
        assert error == pytest.approx(5.0, abs=0.01)

    def test_without_any_height_the_first_width_is_used_and_not_checked(self):
        size, error = batch.pick_size(
            [batch.Size(1, 20, None), batch.Size(2, 30, None)], photo_ratio=2.0
        )
        assert size.variant_id == 1 and error is None

    def test_sizes_with_a_height_are_preferred(self):
        size, error = batch.pick_size(
            [batch.Size(1, 20, None), batch.Size(2, 30, 60)], photo_ratio=2.0
        )
        assert size.variant_id == 2 and error == pytest.approx(0)


# ---------------------------------------------------------------- 描
def photo(tmp_path, name, draw):
    """白底 300 x 300，用 draw(img) 畫上深色的商品，存成 PNG。"""
    img = np.full((300, 300, 3), 255, dtype=np.uint8)
    draw(img)
    path = tmp_path / f"{name}.png"
    Image.fromarray(img).save(path)
    return path


def cylinder(img):  # 高 201 列、寬 81 欄：量出來高 200 px、寬 80 px，高/寬 = 2.5
    img[50:251, 110:191] = 40


def room(img):  # 實景照：有花紋的地板一路到左右邊（單一顏色的地板會被當成背景色）
    img[200:300, :] = np.random.default_rng(0).integers(60, 200, (100, 300, 3))
    cylinder(img)


def lopsided(img):  # 細桿加一支往右伸的手臂
    img[50:251, 140:161] = 40
    img[60:120, 150:290] = 40


class FakeCache:
    def __init__(self, files=None, errors=None):
        self.files, self.errors, self.asked = files or {}, errors or {}, []

    def get(self, url):
        self.asked.append(url)
        if url in self.errors:
            raise self.errors[url]
        return self.files[url]


def cand(url="u", sizes=None, skip=None):
    return batch.Candidate("p", url, sizes if sizes is not None else [batch.Size(7, 20, 50)], skip)


class TestTrace:
    def test_a_good_photo_is_traced_at_the_real_size(self, tmp_path):
        cache = FakeCache({"u": photo(tmp_path, "c", cylinder)})
        r = batch.trace(cand(), cache)
        assert r.status == "ok" and r.variant_id == 7
        assert r.ratio_error_pct == pytest.approx(0, abs=1)
        assert max(x for x, _ in r.lathe) == pytest.approx(10, abs=0.2), "半徑 = 寬 20 cm 的一半"
        assert max(y for _, y in r.lathe) == pytest.approx(50, abs=0.2), "高照標的 50 cm"

    def test_proportions_more_than_15_percent_off_are_kept_but_flagged(self, tmp_path):
        cache = FakeCache({"u": photo(tmp_path, "c", cylinder)})
        r = batch.trace(cand(sizes=[batch.Size(7, 20, 30)]), cache)  # 標的高/寬 1.5，照片 2.5
        assert r.status == "suspect" and r.reason == batch.RATIO_OFF
        assert r.ratio_error_pct == pytest.approx(66.7, abs=1)
        assert max(h for _, h in r.lathe) == pytest.approx(30, abs=0.2), "高照標的 30 cm，不照照片"

    def test_a_room_photo_is_not_traced(self, tmp_path):
        r = batch.trace(cand(), FakeCache({"u": photo(tmp_path, "r", room)}))
        assert (r.status, r.reason, r.lathe) == ("bad_photo", ol.CUT_OFF, None)

    def test_a_lopsided_shape_is_not_traced(self, tmp_path):
        r = batch.trace(cand(), FakeCache({"u": photo(tmp_path, "l", lopsided)}))
        assert (r.status, r.reason, r.lathe) == ("not_round", ol.LOPSIDED, None)

    def test_a_blank_photo_has_no_product(self, tmp_path):
        r = batch.trace(cand(), FakeCache({"u": photo(tmp_path, "b", lambda img: None)}))
        assert r.status == "no_product"

    def test_robots_and_download_errors_are_recorded(self, tmp_path):
        cache = FakeCache(
            errors={"x": photos.BlockedError("robots"), "y": photos.DownloadError("HTTP 500")}
        )
        assert batch.trace(cand("x"), cache).status == "blocked"
        failed = batch.trace(cand("y"), cache)
        assert failed.status == "download_failed" and "500" in failed.reason

    def test_a_broken_file_does_not_crash(self, tmp_path):
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not an image")
        r = batch.trace(cand(), FakeCache({"u": bad}))
        assert r.status == "download_failed"

    def test_a_skipped_product_is_not_downloaded(self):
        cache = FakeCache()
        r = batch.trace(cand(skip=batch.NO_PHOTO, sizes=[]), cache)
        assert (r.status, r.reason) == ("skipped", batch.NO_PHOTO)
        assert cache.asked == []


class TestRun:
    def test_results_are_saved_one_row_per_product(self, tmp_path):
        cache = FakeCache({"u": photo(tmp_path, "c", cylinder)})
        out = batch.Results(tmp_path / "out.db")
        counts = batch.run([cand()], cache, out)
        assert counts == Counter(ok=1)
        row = (
            sqlite3.connect(tmp_path / "out.db")
            .execute("SELECT product_id, status, image_url, variant_id, lathe FROM outline")
            .fetchone()
        )
        assert row[:4] == ("p", "ok", "u", 7)
        assert json.loads(row[4])[0][1] == 0, "lathe 是 [[半徑, 高], ...] 從底部開始"

    def test_a_second_run_skips_finished_products_but_retries_failed_downloads(self, tmp_path):
        good = batch.Candidate("good", "g", [batch.Size(1, 20, 50)], None)
        flaky = batch.Candidate("flaky", "f", [batch.Size(2, 20, 50)], None)
        cache = FakeCache(
            {"g": photo(tmp_path, "c", cylinder)}, errors={"f": photos.DownloadError("timeout")}
        )
        out = batch.Results(tmp_path / "out.db")
        assert batch.run([good, flaky], cache, out) == Counter(ok=1, download_failed=1)
        cache.asked.clear()
        del cache.errors["f"]
        cache.files["f"] = cache.files["g"]
        again = batch.run([good, flaky], cache, batch.Results(tmp_path / "out.db"))
        assert cache.asked == ["f"] and again == Counter(ok=1)

    def test_a_new_photo_url_is_traced_again(self, tmp_path):
        cache = FakeCache(
            {"u": photo(tmp_path, "c", cylinder), "v": photo(tmp_path, "d", cylinder)}
        )
        out = batch.Results(tmp_path / "out.db")
        batch.run([cand("u")], cache, out)
        batch.run([cand("v")], cache, out)
        assert cache.asked == ["u", "v"]

    def test_limit_stops_after_that_many_downloads(self, tmp_path):
        cache = FakeCache({"u": photo(tmp_path, "c", cylinder)})
        cands = [batch.Candidate(f"p{i}", "u", [batch.Size(i, 20, 50)], None) for i in range(5)]
        skipped = batch.Candidate("s", "", [], batch.NO_PHOTO)
        # 不用下載的排在 limit 用完之後，還是照做
        order = [*cands[:2], skipped, *cands[2:]]
        counts = batch.run(order, cache, batch.Results(tmp_path / "out.db"), limit=2)
        assert counts == Counter(skipped=1, ok=2), "沒下載的不算進 limit"

    def test_the_summary_names_every_status_in_chinese(self):
        lines = batch.summary(Counter(ok=3, bad_photo=2))
        assert lines[0].startswith("可以用") and "3" in lines[0]
        assert any("2" in line and "實景" in line for line in lines)


class TestReviewSheet:
    def test_draws_a_random_sample_of_ok_results(self, tmp_path):
        import review

        pic = photo(tmp_path, "c", cylinder)
        out = batch.Results(tmp_path / "out.db")
        for i in range(6):
            out.save(batch.Result(f"p{i}", "ok", image_url="u", lathe=[[10, 0], [10, 50], [0, 50]]))
        out.save(batch.Result("bad", "bad_photo", image_url="u"))
        path = review.sheet(out, lambda url: pic, tmp_path / "review.png", n=5)
        img = Image.open(path)
        cols = review.COLUMNS
        assert img.size == (cols * 2 * review.PANEL, 2 * (review.PANEL + review.LABEL)), (
            "5 件：4 欄 2 列"
        )

    def test_the_same_seed_picks_the_same_products(self, tmp_path):
        import review

        pic = photo(tmp_path, "c", cylinder)
        out = batch.Results(tmp_path / "out.db")
        for i in range(10):
            out.save(batch.Result(f"p{i}", "ok", image_url="u", lathe=[[10, 0], [0, 50]]))
        a = review.sheet(out, lambda url: pic, tmp_path / "a.png", n=3, seed=1)
        b = review.sheet(out, lambda url: pic, tmp_path / "b.png", n=3, seed=1)
        assert a.read_bytes() == b.read_bytes()


class TestCodexReview:
    """Codex 審查找到的（2026-11-21）。"""

    def test_width_and_depth_apart_is_not_round_even_with_a_diameter(self, tmp_path):
        db = make_db(tmp_path / "a.db", [("odd", "table", [(300, 150, 400, 200)], {0: "u"})])
        assert batch.candidates([db])[0].skip == batch.NO_ROUND_SIZE

    def test_new_sizes_get_traced_even_if_the_photo_is_the_same(self, tmp_path):
        cache = FakeCache({"u": photo(tmp_path, "c", cylinder)})
        out = batch.Results(tmp_path / "out.db")
        batch.run([cand(sizes=[], skip=batch.NO_ROUND_SIZE)], cache, out)
        counts = batch.run([cand()], cache, out)  # 資料庫補上了尺寸
        assert counts == Counter(ok=1)

    def test_changed_sizes_are_traced_again(self, tmp_path):
        cache = FakeCache({"u": photo(tmp_path, "c", cylinder)})
        out = batch.Results(tmp_path / "out.db")
        batch.run([cand(sizes=[batch.Size(7, 20, 50)])], cache, out)
        batch.run([cand(sizes=[batch.Size(7, 40, 100)])], cache, out)
        lathe = json.loads(out.db.execute("SELECT lathe FROM outline").fetchone()[0])
        assert max(h for _, h in lathe) == pytest.approx(100, abs=0.2), "用新的尺寸"

    def test_skipped_products_after_the_limit_are_still_recorded(self, tmp_path):
        cache = FakeCache({"u": photo(tmp_path, "c", cylinder)})
        cands = [batch.Candidate(f"p{i}", "u", [batch.Size(i, 20, 50)], None) for i in range(3)]
        skipped = batch.Candidate("s", "", [], batch.NO_PHOTO)
        counts = batch.run([*cands, skipped], cache, batch.Results(tmp_path / "out.db"), limit=2)
        assert counts == Counter(ok=2, skipped=1)

    def test_a_decompression_bomb_does_not_stop_the_batch(self, tmp_path, monkeypatch):
        cache = FakeCache({"u": photo(tmp_path, "c", cylinder)})
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # 300 x 300 的圖就算「太大」
        r = batch.trace(cand(), cache)
        assert r.status == "download_failed"

    def test_photos_and_the_review_sheet_always_stay_in_out(self):
        args = batch.parse_args(["--db", "x.db", "--out", "elsewhere/results.db"])
        assert not hasattr(args, "photos"), "照片的位置不能改：只放 tools/outline/out/photos"
        assert batch.PHOTOS == batch.HERE / "out" / "photos"
        assert batch.REVIEW == batch.HERE / "out" / "review.png"


class TestWallNames:
    def test_a_ceiling_lamp_named_wall_lamp_is_not_a_candidate(self, tmp_path):
        db = make_db(tmp_path / "a.db", [("Clessidra Wall Lamp", "ceiling", ROUND, {0: "u"})])
        assert batch.candidates([db]) == []
