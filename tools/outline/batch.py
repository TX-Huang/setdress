"""對爬到的全部圓形燈批次自動描輪廓（docs/outline.md「批次」）。

    python batch.py --db <softgoods 資料庫> [--db ...] [--limit N] [--sheet 40]

挑商品（吊燈、桌燈、立燈、吸頂燈，有圓的尺寸、有照片）
→ 下載第一張照片（photos.py，只在本機）
→ 看照片能不能用（outline.photo_problem）
→ 描輪廓、照最接近的尺寸縮放 → 一件一列存進 out/outlines.db。
再跑一次只做還沒做的；下載失敗的會再試，照片換了也會重描。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

import outline as ol
import photos

HERE = pathlib.Path(__file__).resolve().parent
PHOTOS = HERE / "out" / "photos"  # 店家的照片：只在本機（.gitignore 擋著 tools/outline/out/）
REVIEW = HERE / "out" / "review.png"  # 抽查圖裡有店家的照片，也只在本機
ROUND_KINDS = ("pendant", "table", "floor", "ceiling")  # 壁燈、燈泡、戶外燈不挑
# 種類 → 要描的分類（大類/小類）。decor：其他軟裝裡「轉一圈」的（docs/decor.md）
KINDS = {
    "lamps": tuple(f"lighting/{k}" for k in ROUND_KINDS),
    "decor": ("decor/vase", "greenery/planter"),
}
ROUND_TOLERANCE = 0.10  # 寬和深差這麼多以內，算圓的
RATIO_LIMIT_PCT = 15  # 照片的高寬比跟標的差超過這麼多，要人看
MAX_SIDE = 600  # 照片縮到這麼大再描（跟 run_photos.py 一樣）
RETRY = ("download_failed",)  # 這些狀態下次跑會再試

WALL = re.compile(r"wall|壁燈|壁掛|壁式", re.IGNORECASE)
CEILING = re.compile(r"ceiling|吸頂", re.IGNORECASE)


def wall_name(name: str) -> bool:
    """名字寫壁燈、沒寫吸頂：店家分類分錯了（Codex 審查：Clessidra Wall Lamp 被分到吸頂燈）。"""
    return bool(WALL.search(name or "")) and not CEILING.search(name or "")


NO_ROUND_SIZE = "沒有圓的尺寸（要有直徑，或寬和深差不到一成）"
NO_PHOTO = "沒有照片"
RATIO_OFF = "照片的高寬比跟標的尺寸差超過 15%，要人看"

STATUS_TEXT = {
    "ok": "可以用",
    "suspect": "比例對不上，要人看",
    "bad_photo": "實景照或照片切到商品",
    "not_round": "不是轉一圈的形狀",
    "no_product": "照片裡找不到商品",
    "blocked": "robots 不讓抓",
    "download_failed": "下載失敗（下次再試）",
    "skipped": "沒下載（沒照片或沒有圓的尺寸）",
}


@dataclass(frozen=True)
class Size:
    variant_id: int
    width_cm: float
    height_cm: float | None


@dataclass(frozen=True)
class Candidate:
    product_id: str
    image_url: str
    sizes: list[Size]
    skip: str | None  # 不用下載的原因；None = 要描


@dataclass
class Result:
    product_id: str
    status: str
    reason: str | None = None
    image_url: str = ""
    variant_id: int | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    ratio_error_pct: float | None = None
    lathe: list[list[float]] | None = field(default=None)


# ---------------------------------------------------------------- 挑商品
_SQL = """
SELECT p.product_id, p.model, v.variant_id, v.width_mm, v.depth_mm, v.height_mm, v.diameter_mm,
       (SELECT src_url FROM image vi WHERE vi.variant_id = v.variant_id
        ORDER BY vi.position, vi.image_id LIMIT 1),
       (SELECT src_url FROM image i WHERE i.product_id = p.product_id
        ORDER BY i.position, i.image_id LIMIT 1)
FROM product p LEFT JOIN variant v ON v.product_id = p.product_id
WHERE p.cat1 || '/' || p.cat2 IN ({})
ORDER BY p.product_id, v.variant_id
"""


def _is_round(w, d) -> bool:
    """寬和深差不到一成；只標了其中一個（或只有直徑）也算。

    有直徑也要看寬和深：寬 30、深 15、直徑 20 這種不是圓的（Codex 審查）。
    """
    return not (w and d) or abs(w - d) <= ROUND_TOLERANCE * max(w, d)


def _round_size(variant_id, w, d, h, dia) -> Size | None:
    """圓的尺寸換成公分（資料庫是 mm）；不是圓的、沒有寬度的回 None。"""
    width = dia or w
    if not width or not _is_round(w, d):
        return None
    return Size(variant_id, width / 10, h / 10 if h else None)


def _open_ro(path: pathlib.Path | str) -> sqlite3.Connection:
    return sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def _rows_by_product(path, kind: str = "lamps") -> dict[str, list[tuple]]:
    cats = KINDS[kind]
    with closing(_open_ro(path)) as db:
        rows = db.execute(_SQL.format(", ".join("?" * len(cats))), cats).fetchall()
    grouped: dict[str, list[tuple]] = {}
    for pid, _model, *rest in (r for r in rows if not wall_name(r[1])):
        grouped.setdefault(pid, []).append(tuple(rest))
    return grouped


def _round_sizes(rows: list[tuple]) -> tuple[dict[tuple, Size], str | None]:
    """圓的尺寸（好幾個顏色同一個尺寸：留第一個），和第一個「有自己照片」的款式的照片。

    有自己照片的款式，它的尺寸就用它（描的是它的照片，顏色、款式名才對得上）。
    """
    sizes: dict[tuple, Size] = {}
    own = None
    for vid, w, d, h, dia, vimg, _ in rows:
        size = _round_size(vid, w, d, h, dia)
        if not size:
            continue
        key = (size.width_cm, size.height_cm)
        if vimg and own is None:
            own, sizes[key] = vimg, size
        else:
            sizes.setdefault(key, size)
    return sizes, own


def _candidate(pid: str, rows: list[tuple]) -> Candidate:
    sizes, own = _round_sizes(rows)
    image = own or rows[0][-1] or ""
    skip = NO_ROUND_SIZE if not sizes else NO_PHOTO if not image else None
    return Candidate(pid, image, list(sizes.values()), skip)


def candidates(db_paths: list, kind: str = "lamps") -> list[Candidate]:
    """每個資料庫裡這個種類的商品（lamps：吊燈、桌燈、立燈、吸頂燈；decor：花瓶、花器）。

    同一件商品出現在好幾個資料庫，用第一個。
    """
    found: dict[str, Candidate] = {}
    for path in db_paths:
        for pid, rows in _rows_by_product(path, kind).items():
            if pid not in found:
                found[pid] = _candidate(pid, rows)
    return list(found.values())


def pick_size(sizes: list[Size], photo_ratio: float) -> tuple[Size, float | None]:
    """跟照片的「高 ÷ 寬」最接近的尺寸，和差幾 %。都沒標高度：用第一個，不檢查（None）。"""
    tall = [s for s in sizes if s.height_cm]
    if not tall:
        return sizes[0], None

    def error(s: Size) -> float:
        store = s.height_cm / s.width_cm
        return 100 * (photo_ratio - store) / store

    best = min(tall, key=lambda s: abs(error(s)))
    return best, error(best)


# ---------------------------------------------------------------- 描
def _load(path: pathlib.Path) -> np.ndarray:
    with Image.open(path) as img:
        img.draft("RGB", (MAX_SIDE, MAX_SIDE))  # JPEG 解碼時就縮小：大照片不佔記憶體（Codex 審查）
        clear = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
        img = img.convert("RGBA" if clear else "RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        return np.asarray(img)


def _scaled(c: Candidate, prof: ol.PixelProfile) -> Result:
    _, photo_ratio = ol.to_cm(prof, 1.0)  # 寬當成 1：量出來的高度就是高寬比
    size, error = pick_size(c.sizes, photo_ratio)
    pts, _ = ol.to_cm(prof, size.width_cm, size.height_cm)
    lathe = [[round(r, 1), round(h, 1)] for r, h in ol.simplify(pts, tol=0.01 * size.width_cm)]
    off = error is not None and abs(error) > RATIO_LIMIT_PCT
    return Result(
        c.product_id,
        "suspect" if off else "ok",
        RATIO_OFF if off else None,
        c.image_url,
        size.variant_id,
        size.width_cm,
        size.height_cm,
        None if error is None else round(error, 1),
        lathe,
    )


def _failure(e: Exception) -> str:
    if isinstance(e, photos.BlockedError):
        return "blocked"
    return "no_product" if isinstance(e, ol.NoProductError) else "download_failed"


def trace(c: Candidate, cache) -> Result:
    """一件商品：下載、檢查、描。哪一步失敗都只回結果，不丟例外（一張照片不讓整批停）。"""
    if c.skip:
        return Result(c.product_id, "skipped", c.skip, c.image_url)
    try:
        mask = ol.foreground(_load(cache.get(c.image_url)))
        problem = ol.photo_problem(mask)
        if problem:
            status = "bad_photo" if problem == ol.CUT_OFF else "not_round"
            return Result(c.product_id, status, problem, c.image_url)
        return _scaled(c, ol.profile(mask))
    except (
        photos.BlockedError,
        photos.DownloadError,
        ol.NoProductError,
        OSError,  # Pillow 打不開的檔案
        Image.DecompressionBombError,  # 像素多到解碼會吃光記憶體
    ) as e:
        return Result(c.product_id, _failure(e), str(e), c.image_url)


# ---------------------------------------------------------------- 存結果
_SCHEMA = """
CREATE TABLE IF NOT EXISTS outline (
    product_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    reason TEXT,
    image_url TEXT NOT NULL,
    variant_id INTEGER,
    width_cm REAL,
    height_cm REAL,
    ratio_error_pct REAL,
    -- lathe：JSON [[半徑 cm, 高 cm], ...] 由下往上，跟原型 lamps.js 的 traced 一樣
    lathe TEXT,
    sizes TEXT,              -- 描的時候有哪些尺寸（JSON）：尺寸改了要重描
    traced_at TEXT DEFAULT (datetime('now'))
);
"""


def sizes_key(c: Candidate) -> str:
    return json.dumps([[s.variant_id, s.width_cm, s.height_cm] for s in c.sizes])


class Results:
    def __init__(self, path: pathlib.Path | str):
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(_SCHEMA)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(outline)")}
        if "sizes" not in columns:  # 舊的結果檔：補上欄位，舊的那些會重描一次
            self.db.execute("ALTER TABLE outline ADD COLUMN sizes TEXT")

    def done(self, c: Candidate) -> bool:
        """做過了、不用再做：同一張照片、同樣的尺寸，而且不是下載失敗。"""
        row = self.db.execute(
            "SELECT status, image_url, sizes FROM outline WHERE product_id = ?", (c.product_id,)
        ).fetchone()
        return row is not None and row[0] not in RETRY and row[1:] == (c.image_url, sizes_key(c))

    def save(self, r: Result, sizes: str | None = None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO outline (product_id, status, reason, image_url, variant_id,"
            " width_cm, height_cm, ratio_error_pct, lathe, sizes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r.product_id,
                r.status,
                r.reason,
                r.image_url,
                r.variant_id,
                r.width_cm,
                r.height_cm,
                r.ratio_error_pct,
                None if r.lathe is None else json.dumps(r.lathe),
                sizes,
            ),
        )
        self.db.commit()

    def counts(self) -> Counter:
        return Counter(
            dict(self.db.execute("SELECT status, COUNT(*) FROM outline GROUP BY status"))
        )


def run(
    cands: list[Candidate],
    cache,
    results: Results,
    *,
    limit: int | None = None,
    log=lambda line: None,
) -> Counter:
    """還沒做的一件一件做。limit：最多試幾張照片（不用下載的不算）。回這一輪各狀態幾件。"""
    counts, tried = Counter(), 0
    for c in (c for c in cands if not results.done(c)):
        if _used_up(limit, tried, c):
            continue  # 後面不用下載的還是要記（Codex 審查）
        r = trace(c, cache)
        results.save(r, sizes_key(c))
        counts[r.status] += 1
        if not c.skip:
            tried += 1
            _progress(tried, counts, log)
    return counts


def _used_up(limit: int | None, tried: int, c: Candidate) -> bool:
    """limit 只算要下載的；不用下載的（skip）一律照做。"""
    return not c.skip and limit is not None and tried >= limit


def _progress(tried: int, counts: Counter, log) -> None:
    if tried % 100 == 0:
        log(f"  試了 {tried} 張照片：{dict(counts)}")


def summary(counts: Counter) -> list[str]:
    return [f"{STATUS_TEXT[s]}：{counts[s]} 件" for s in STATUS_TEXT if counts[s]]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """照片和抽查圖（有店家的照片）的位置不能改：只放 .gitignore 擋著的 out/（Codex 審查）。"""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", action="append", required=True, help="softgoods 的資料庫，可以給好幾個")
    ap.add_argument("--out", type=pathlib.Path, default=HERE / "out" / "outlines.db")
    ap.add_argument(
        "--kind", choices=sorted(KINDS), default="lamps", help="lamps 燈；decor 花瓶、花器"
    )
    ap.add_argument("--limit", type=int, help="最多試幾張照片（先小跑看看）")
    ap.add_argument(
        "--sheet", type=int, default=0, help="隨機抽幾件「可以用」的畫成 out/review.png 給人看"
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    cands = candidates(args.db, args.kind)
    print(f"候選：{len(cands)} 件（要描 {sum(not c.skip for c in cands)} 件）")
    results, cache = Results(args.out), photos.PhotoCache(PHOTOS)
    counts = run(cands, cache, results, limit=args.limit, log=print)
    print("這一輪：", *summary(counts), sep="\n  ")
    print("全部：", *summary(results.counts()), sep="\n  ")
    if args.sheet:
        import review  # 只有要畫圖時才用到

        path = review.sheet(results, cache, REVIEW, n=args.sheet)
        print(f"抽查圖：{path}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
