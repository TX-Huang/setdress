"""地毯：尺寸、各家價格、照片能不能當花紋 → prototype/rugs.js（docs/rugs.md）。

    python rugs.py --db <softgoods 資料庫>

地毯是平的：從正上方拍、單色背景的商品照可以直接當花紋。這裡在本機看照片，
記下地毯在照片裡的範圍（外框）和外形（沿著邊描的點）；網站只放照片的連結，
打開網頁時瀏覽器才從店家讀照片（照片不複製進網站）。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from urllib.parse import urlsplit

import numpy as np

import batch
import export_catalog as ex
import outline as ol
import photos

OUT = batch.HERE.parents[1] / "prototype" / "rugs.js"
GREY = 0x9C978F  # 照片下載不到時的顏色
RATIO_OFF = 0.20  # 照片裡的長寬比跟標的差這麼多以內
MIN_FILL = 0.5  # 地毯至少佔它外框的一半
ROUND_FILL = 0.9  # 圓的地毯大約佔外框的 79%（π/4），方的接近 100%
SLANT_FILL = 0.95  # 外形只有四個角、卻填不滿外框：斜著拍的梯形（或轉了角度的方形）
HOTLINK_HOSTS = {"cdn.shopify.com", "img.shoplineapp.com"}  # 允許別的網站讀（CORS），可以當 3D 貼圖

Size = tuple  # ("rect", 長邊 cm, 短邊 cm) 或 ("round", 直徑, 直徑)


# ---------------------------------------------------------------- 尺寸
def _is_round(w, d, dia) -> bool:
    """只有直徑；或寬、深、直徑都一樣（有的店圓的也寫寬、深）。"""
    return bool(dia) and (not (w and d) or w == d == dia)


def rug_size(w, d, dia) -> Size | None:
    """資料庫的尺寸（mm）→ 地毯的形狀和大小（cm）。直的橫的算同一個尺寸。"""
    if _is_round(w, d, dia):
        return ("round", dia / 10, dia / 10)
    if w and d:
        return ("rect", max(w, d) / 10, min(w, d) / 10)
    return None


_ROWS = """
SELECT p.product_id, b.name, p.model, v.variant_id, v.name, v.width_mm, v.depth_mm, v.height_mm,
       v.diameter_mm, v.pack, s.name, l.price, l.in_stock, l.url, l.gone_at, l.last_seen_at
FROM product p JOIN brand b ON b.brand_id = p.brand_id
JOIN variant v ON v.product_id = p.product_id
LEFT JOIN listing l ON l.variant_id = v.variant_id
LEFT JOIN site s ON s.site_id = l.site_id
WHERE p.cat1 = 'textile' AND p.cat2 = 'rug'
ORDER BY p.product_id, v.variant_id
"""
_PHOTOS = """
SELECT i.product_id, i.variant_id, i.src_url
FROM image i JOIN product p ON p.product_id = i.product_id
WHERE p.cat1 = 'textile' AND p.cat2 = 'rug' ORDER BY i.product_id, i.position, i.image_id
"""


def _open(path) -> closing:
    return closing(sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro", uri=True))


def _size_of(row) -> Size | None:
    return rug_size(row[2], row[3], row[5])


def _counted(rows: list[tuple], size: Size, single: bool) -> list[tuple]:
    """算進這個尺寸的列：同尺寸；只有一個尺寸時，沒標尺寸的也算。"""
    return [r for r in rows if _belongs(r, size, single) and ex._usable(r)]


def _belongs(row, size: Size, single: bool) -> bool:
    own = _size_of(row)
    return own == size or (single and not own)


def _cheapest(counted: list[tuple]) -> list[dict]:
    """每家取最便宜的，照價格排。"""
    best: dict[str, tuple] = {}
    for r in sorted(counted, key=lambda r: r[8], reverse=True):
        best[r[7]] = r  # 從貴排到便宜，同一家最後留最便宜的
    return sorted(map(ex._offer, best.values()), key=lambda o: (o["price"], o["store"]))


def _sizes(rows: list[tuple]) -> list[dict]:
    """每個尺寸一列，各自的各家價格；沒有任何價格的尺寸不放。"""
    known = sorted({_size_of(r) for r in rows} - {None}, key=lambda s: (s[1] * s[2], s))
    out = []
    for size in known:
        counted = _counted(rows, size, len(known) == 1)
        deals = _cheapest(counted)
        if deals:
            out.append(
                {
                    "shape": size[0],
                    "w": size[1],
                    "d": size[2],
                    "offers": deals,
                    "seen": _seen(counted),
                }
            )
    return out


def _seen(counted: list[tuple]) -> str:
    return max(((r[12] or "")[:10] for r in counted), default="")


def _photo_choice(rows: list[tuple], photos_of: list[tuple]) -> tuple[str, str | None]:
    """(照片網址, 它是哪個款式自己的)：有尺寸的款式自己的照片優先，沒有就用商品第一張。"""
    own = _own_photos(rows, photos_of)
    first = (photos_of[0][1], None) if photos_of else ("", None)
    return own[0] if own else first


def _own_photos(rows: list[tuple], photos_of: list[tuple]) -> list[tuple]:
    """有尺寸的款式自己的照片：[(網址, 款式 id)]。"""
    sized = {r[0] for r in rows if _size_of(r)}
    return [(url, vid) for vid, url in photos_of if vid in sized]


def _variant_label(rows: list[tuple], own_vid: str | None) -> str:
    """照片是哪個款式的，就寫那個款式的名稱；只有一種名稱也寫；其他不寫（不知道照片是哪個顏色）。"""
    if own_vid:
        return next((r[1] for r in rows if r[0] == own_vid), "") or ""
    names = _names(rows)
    return next(iter(names)) if len(names) == 1 else ""


def _names(rows: list[tuple]) -> set:
    return {r[1] for r in rows if _size_of(r)} - ex.PLACEHOLDER - {None, ""}


def _read(db_path) -> tuple[list, list]:
    with _open(db_path) as db:
        return db.execute(_ROWS).fetchall(), db.execute(_PHOTOS).fetchall()


def _read_all(db_paths) -> tuple[list, list]:
    rows, pics = [], []
    for path in db_paths:
        more_rows, more_pics = _read(path)
        rows += more_rows
        pics += more_pics
    return rows, pics


def _group(rows: list[tuple]) -> dict[str, list[tuple]]:
    """第一欄（商品 id）→ 那些列的其他欄。"""
    out: dict[str, list[tuple]] = {}
    for pid, *rest in rows:
        out.setdefault(pid, []).append(tuple(rest))
    return out


def load(*db_paths) -> dict[str, dict]:
    """地毯商品 id → 品牌、型號、款式、尺寸（各自的價格）、要用的照片。沒有任何尺寸有價格的不放。

    好幾個資料庫：同一件商品的列先合起來再算，各家的價格都留著。
    """
    rows, pics = _read_all(db_paths)
    by_pid, pics_of = _group(rows), _group(pics)
    found = {}
    for pid, prows in by_pid.items():
        variant_rows = [
            r[2:] for r in prows
        ]  # (variant_id, 名稱, 寬, 深, 高, 直徑, 幾件一組, 店, 價格, ...)
        sizes = _sizes(variant_rows)
        if sizes:
            url, own = _photo_choice(variant_rows, pics_of.get(pid, []))
            brand, model = prows[0][0], prows[0][1]
            found[pid] = {"brand": brand, "name": model, "sizes": sizes, "photo_url": url,
                          "variant": _variant_label(variant_rows, own)}  # fmt: skip
    return found


# ---------------------------------------------------------------- 照片
def can_hotlink(url: str) -> bool:
    return urlsplit(url).netloc in HOTLINK_HOSTS


def _box(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _fits(box, shape, size: Size) -> bool:
    """沒碰到邊、長寬比跟標的差不到兩成。"""
    x0, y0, x1, y1 = box
    h, w = shape
    if x0 == 0 or y0 == 0 or x1 == w or y1 == h:
        return False
    bw, bh = x1 - x0, y1 - y0
    ratio = max(bw, bh) / min(bw, bh)
    return abs(ratio / (size[1] / size[2]) - 1) <= RATIO_OFF


def _outline(mask: np.ndarray, box) -> list[list[float]]:
    """沿著邊描：每一列的最左、最右，換成外框裡的 0 到 1，再簡化。"""
    x0, y0, x1, y1 = box
    rows, left, right = ol._row_extents(mask)
    w, h = x1 - x0, y1 - y0
    lefts = [((lx - x0) / w, (r - y0) / h) for r, lx in zip(rows, left, strict=True)]
    rights = [((rx + 1 - x0) / w, (r + 1 - y0) / h) for r, rx in zip(rows, right, strict=True)]
    ring = lefts + rights[::-1]
    return [[round(u, 4), round(v, 4)] for u, v in ol.simplify(ring, tol=0.005)]


def layout(rgb: np.ndarray, size: Size) -> dict | None:
    """照片可以當花紋的話，回 {crop: 外框（照片的 0 到 1）, outline: 外形}；不行回 None。"""
    mask = ol.foreground(rgb)
    box = _box(mask)
    if box is None or not _fits(box, mask.shape, size):
        return None
    x0, y0, x1, y1 = box
    if mask[y0:y1, x0:x1].mean() < MIN_FILL:
        return None
    h, w = mask.shape
    crop = [round(x0 / w, 4), round(y0 / h, 4), round(x1 / w, 4), round(y1 / h, 4)]
    outline = _outline(mask, box)
    if _slanted(outline):
        return None
    wide = x1 - x0 >= y1 - y0  # 照片裡地毯是橫的：長邊左右
    return {"crop": crop, "outline": outline, "wide": wide}


def _slanted(outline: list[list[float]]) -> bool:
    """四個角的形狀卻填不滿外框：斜著拍或轉了角度，貼上去會歪（Codex 審查）。"""
    return len(outline) <= 4 and _area(outline) < SLANT_FILL


def colour(rgb: np.ndarray) -> int:
    """地毯那一塊的中位數顏色；找不到地毯就用中性灰。"""
    mask = ol.foreground(rgb)
    if not mask.any():
        return GREY
    r, g, b = (int(v) for v in np.median(rgb[..., :3][mask], axis=0))
    return (r << 16) | (g << 8) | b


# ---------------------------------------------------------------- 整份
def _rgb(local: pathlib.Path | None) -> np.ndarray | None:
    if local is None or not local.exists():
        return None
    try:
        return batch._load(local)
    except OSError:
        return None


def _area(ring: list[list[float]]) -> float:
    """外形圍起來的面積（外框當 1 x 1）。回 Python 的數字（numpy 的 True/False 寫不進 JSON）。"""
    pairs = zip(ring, ring[1:] + ring[:1], strict=True)
    return float(abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in pairs))) / 2


def _one_shape(sizes: list[dict], fits: list[bool], outline: list) -> list[bool]:
    """圓的尺寸：照片裡的地毯要看起來是圓的。方的尺寸（寬 x 長）：橢圓、不規則的也算，
    除非照片是圓的、而且有圓的尺寸可以用（直徑 200 和 200 x 200 都對得上時）。"""
    looks_round = _area(outline) < ROUND_FILL
    round_used = looks_round and _any_round(sizes, fits)
    return [
        ok and (looks_round if _round(s) else not round_used)
        for s, ok in zip(sizes, fits, strict=True)
    ]


def _any_round(sizes: list[dict], fits: list[bool]) -> bool:
    return any(ok for s, ok in zip(sizes, fits, strict=True) if _round(s))


def _round(size: dict) -> bool:
    return size["shape"] == "round"


def _layouts(rgb: np.ndarray, sizes: list[dict]) -> list[dict | None]:
    return [layout(rgb, (s["shape"], s["w"], s["d"])) for s in sizes]


def _fitting(rgb: np.ndarray, sizes: list[dict]) -> tuple[dict | None, list[bool]]:
    """(照片的外框和外形, 每個尺寸能不能用這張照片)。

    同一張照片、不同尺寸的長寬比可能不一樣：長寬比對得上的尺寸才用。
    """
    lays = _layouts(rgb, sizes)
    found = next((lay for lay in lays if lay), None)
    if found is None:
        return None, [False] * len(sizes)
    fits = _one_shape(sizes, [lay is not None for lay in lays], found["outline"])
    return (found, fits) if any(fits) else (None, fits)


def _looks(
    url: str, sizes: list[dict], local: pathlib.Path | None
) -> tuple[dict | None, list, int]:
    """(照片花紋或 None, 每個尺寸能不能用照片, 顏色)。店家伺服器要允許別的網站讀。"""
    rgb = _rgb(local)
    none = [False] * len(sizes)
    if rgb is None:
        return None, none, GREY
    found, fits = _fitting(rgb, sizes) if can_hotlink(url) else (None, none)
    photo = {"url": photos.smaller_url(url), **found} if found else None
    return photo, fits, colour(rgb)


def _item(pid: str, p: dict, photo_for) -> dict:
    photo, fits, col = _looks(
        p["photo_url"], p["sizes"], photo_for(p["photo_url"]) if p["photo_url"] else None
    )
    sizes = [
        {**{k: s[k] for k in ("shape", "w", "d", "offers")}, "photoFits": ok}
        for s, ok in zip(p["sizes"], fits, strict=True)
    ]
    return {
        "id": f"r:{pid}",
        "brand": p["brand"],
        "name": p["name"],
        "variant": p["variant"],
        "category": "地毯",
        "sizes": sizes,
        "photo": photo,
        "colour": col,
        "updated": max(s["seen"] for s in p["sizes"]),
    }


def build(db_paths: list, photo_for: Callable[[str], pathlib.Path | None]) -> dict:
    items = [_item(pid, p, photo_for) for pid, p in sorted(load(*db_paths).items())]
    return {"updated": max((i["updated"] for i in items), default=""), "items": items}


HEADER = """/* 自動產生，不要手改：tools/outline/rugs.py（說明在 docs/rugs.md）
 * 爬到的地毯：品牌、型號、各尺寸的各家價格；照片只有連結（打開網頁時從店家讀），
 * 加上地毯在照片裡的範圍和外形。照片本身不在這裡。
 */
"""


def write(data: dict, path: pathlib.Path) -> None:
    body = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    body = body.replace(',{"brand"', ',\n{"brand"')  # 一件一行
    text = (
        HEADER
        + "(function (root, data) {\n"
        + "  if (typeof module === 'object' && module.exports) module.exports = data;\n"
        + "  else root.SetdressRugs = data;\n"
        + "})(typeof self !== 'undefined' ? self : this, "
        + body
        + ");\n"
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def _download(cache: photos.PhotoCache) -> Callable[[str], pathlib.Path | None]:
    """要量顏色、看形狀才下載（只在本機；照 robots、每個主機隔 1 秒）。"""

    def get(url: str) -> pathlib.Path | None:
        try:
            return cache.get(url)
        except (photos.BlockedError, photos.DownloadError):
            return None

    return get


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", action="append", required=True, help="softgoods 的資料庫，可以給好幾個")
    ap.add_argument("--out", type=pathlib.Path, default=OUT)
    args = ap.parse_args(argv)
    data = build(args.db, photo_for=_download(photos.PhotoCache(batch.PHOTOS)))
    write(data, args.out)
    with_photo = sum(i["photo"] is not None for i in data["items"])
    print(f"寫好 {args.out}：{len(data['items'])} 件地毯，{with_photo} 件用照片當花紋")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
