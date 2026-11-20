"""把自動描「可以用」的燈匯出成網站用的 prototype/catalog.js（docs/catalog.md「資料」）。

    python export_catalog.py --db <softgoods 資料庫> [--db ...]

每盞：品牌、型號、類別、描的時候用的尺寸、各家價格（同尺寸）、輪廓、照片量的顏色、燈泡位置。
照片只拿來量顏色，不放進檔案（照片和照片連結都不上網站）。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from itertools import pairwise

import numpy as np

import batch
import outline as ol

ROOT = batch.HERE.parents[1]
# 種類：哪些分類（大類/小類 → 網頁上的類別）、id 開頭、寫到哪個檔案、網頁上的變數名稱
KINDS = {
    "lamps": {
        "categories": {
            "lighting/pendant": "吊燈",
            "lighting/table": "桌燈",
            "lighting/floor": "立燈",
            "lighting/ceiling": "吸頂燈",
        },
        "prefix": "c:", "key": "lamps", "global": "SetdressCatalog",
        "out": ROOT / "prototype" / "catalog.js",
    },
    "decor": {  # 其他軟裝裡「轉一圈」的（docs/decor.md）
        "categories": {"decor/vase": "花瓶", "greenery/planter": "花器"},
        "prefix": "d:", "key": "items", "global": "SetdressDecor",
        "out": ROOT / "prototype" / "decor.js",
    },
}  # fmt: skip
FLOOR_FROM_CM = 60  # 擺飾這麼高以上放地上（落地花瓶、大盆），其他放桌上
MAX_BANDS = 4
MIN_BAND = 0.1  # 每段至少全高的一成
SPLIT = 40.0  # 相鄰兩段的顏色差這麼多以上才分開（RGB 距離）
BINS = 60  # 量顏色時把高度分成幾格
EDGE = 2  # 每一列左右各丟掉幾 px（邊緣混到背景色）
LIGHT_LUMA = 165  # 亮度這麼高以上是淺色：當燈罩（開燈會亮）
GREY = 0x9A9A98  # 沒有照片時的顏色
OPEN_BOTTOM = 0.6  # 吊燈、吸頂燈底部半徑是最寬的幾成以上，算開口往下
PLACEHOLDER = {"標準", "Default Title", "預設"}  # 店家沒取款式名時填的字，不寫出來
# 款式名裡的顏色字。照片是商品的第一張，不知道是哪個顏色：有好幾個顏色時就不寫款式名
COLOUR_WORD = re.compile(
    r"[白黑紅藍綠黃灰金銀銅粉紫橙橘棕褐米鉻]|咖啡|象牙|透明|"
    r"white|black|red|blue|green|yellow|gr[ae]y|gold|silver|brass|copper|bronze|pink|purple|"
    r"orange|brown|beige|ivory|opal|chrome|natural|sand|clear|smoke",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- 讀資料庫
def _open(path) -> closing:
    """唯讀打開；用完一定關（Windows 上沒關的檔案刪不掉）。"""
    return closing(sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro", uri=True))


_LISTINGS = """
SELECT v.product_id, v.variant_id, v.name, v.width_mm, v.depth_mm, v.height_mm, v.diameter_mm,
       v.pack, s.name, l.price, l.in_stock, l.url, l.gone_at, l.last_seen_at
FROM variant v LEFT JOIN listing l ON l.variant_id = v.variant_id
LEFT JOIN site s ON s.site_id = l.site_id
"""  # 沒有通路的款式也要：「這個商品有幾種尺寸」看全部款式
_PRODUCTS = """
SELECT p.product_id, b.name, p.model, p.cat1 || '/' || p.cat2
FROM product p JOIN brand b ON b.brand_id = p.brand_id
"""


def load_listings(db_paths: list) -> dict[str, list[tuple]]:
    """商品 id → 每個款式在每個通路的一列（沒有通路的款式也有一列，價格是空的）。

    每個資料庫都讀；同一個款式、同一個網址只留第一次看到的。
    """
    found: dict[str, dict[tuple, tuple]] = {}
    for path in db_paths:
        with _open(path) as db:
            for row in db.execute(_LISTINGS):
                found.setdefault(row[0], {}).setdefault((row[1], row[11]), row[1:])
    return {pid: list(rows.values()) for pid, rows in found.items()}


def load_variant_photos(db_paths: list) -> dict[str, set[str]]:
    """款式 id → 它自己的照片（店家有給的才有）。"""
    found: dict[str, set[str]] = {}
    for path in db_paths:
        with _open(path) as db:
            for vid, url in db.execute(
                "SELECT variant_id, src_url FROM image WHERE variant_id IS NOT NULL"
            ):
                found.setdefault(vid, set()).add(url)
    return found


def load_products(db_paths: list) -> dict[str, tuple[str, str, str]]:
    """商品 id → (品牌, 型號, 「大類/小類」)。"""
    found: dict[str, tuple[str, str, str]] = {}
    for path in db_paths:
        with _open(path) as db:
            for pid, brand, model, cat in db.execute(_PRODUCTS):
                found.setdefault(pid, (brand, model, cat))
    return found


# ---------------------------------------------------------------- 價格
def _size_of(row) -> tuple[float, float | None] | None:
    s = batch._round_size(row[0], row[2], row[3], row[4], row[5])
    return None if s is None else (s.width_cm, s.height_cm)


def _no_size(row) -> bool:
    """寬、深、高、直徑都沒標（只標高度的不算：不知道是不是同一個尺寸）。"""
    return not (row[2] or row[3] or row[4] or row[5])


def _usable(row) -> bool:
    """一盞一組、還沒下架、有價格、連結是網址（不放 javascript: 這種，Codex 審查）。"""
    return (row[6] or 1) == 1 and row[11] is None and (row[8] or 0) > 0 and _web_link(row[10])


def _web_link(url) -> bool:
    return str(url or "").startswith(("https://", "http://"))


def _counts(row, size, single: bool) -> bool:
    """這一列算不算這個尺寸的價格。"""
    same = _size_of(row) == size or (single and _no_size(row))
    return same and _usable(row)


STOCK = {1: "in", 0: "out", None: "unknown"}


def offers(rows: list[tuple], size: tuple[float, float | None]) -> list[dict]:
    """跟描的尺寸一樣大的各家價格；每家取最便宜的。商品只有一種尺寸時，沒標尺寸的也算。"""
    best: dict[str, tuple] = {}
    for r in sorted(_counted(rows, size), key=lambda r: r[8], reverse=True):
        best[r[7]] = r  # 從貴排到便宜，同一家最後留下最便宜的
    return sorted(map(_offer, best.values()), key=lambda o: (o["price"], o["store"]))


def _counted(rows: list[tuple], size: tuple[float, float | None]) -> list[tuple]:
    """算進這個尺寸的那幾列。"""
    single = len({_size_of(r) for r in rows} - {None}) == 1
    return [r for r in rows if _counts(r, tuple(size), single)]


def _offer(r: tuple) -> dict:
    return {"store": r[7], "price": int(r[8]), "stock": STOCK.get(r[9], "unknown"), "url": r[10]}


def _updated(counted: list[tuple]) -> str:
    """資料日期：算進價格的那幾列，最後一次看到是哪一天（別的尺寸不算，Codex 審查）。"""
    return max(((r[12] or "")[:10] for r in counted), default="")


# ---------------------------------------------------------------- 顏色
def material(rgb) -> str:
    """淺色當燈罩（開燈會亮），深色或很鮮豔的當金屬。"""
    r, g, b = (float(v) for v in rgb)
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "shade" if luma >= LIGHT_LUMA and max(r, g, b) - min(r, g, b) < 80 else "metal"


def _row_colours(rgb: np.ndarray) -> np.ndarray:
    """商品每一列的中間色（中位數），由下往上；電線剪掉、左右邊緣不算。"""
    mask = ol.foreground(rgb)
    rows, left, right = ol._row_extents(mask)
    if len(rows) == 0:
        raise ol.NoProductError("照片裡找不到商品")
    cut = ol._cord_rows(rows, right - left)
    colours = [
        _row_colour(rgb, mask, r, lo, hi)
        for r, lo, hi in zip(rows[cut:], left[cut:], right[cut:], strict=True)
    ]
    out = np.array(colours[::-1], dtype=float)  # 由下往上
    return out[~np.isnan(out).any(axis=1)]


def _row_colour(rgb: np.ndarray, mask: np.ndarray, r: int, lo: int, hi: int) -> np.ndarray:
    """一列商品的中位數顏色；夠寬的話左右各丟掉 EDGE px。沒有像素回 NaN。"""
    if hi - lo > 2 * EDGE:
        lo, hi = lo + EDGE, hi - EDGE
    px = rgb[r, lo : hi + 1][mask[r, lo : hi + 1]]
    return np.median(px[:, :3], axis=0) if len(px) else np.full(3, np.nan)


def _binned(colours: np.ndarray) -> np.ndarray:
    edges = np.linspace(0, len(colours), min(BINS, len(colours)) + 1).astype(int)
    return np.array([np.median(colours[a:b], axis=0) for a, b in pairwise(edges)])


def _cost(prefix: np.ndarray, prefix2: np.ndarray, a: int, b: int) -> float:
    """第 a 到 b-1 格當成同一段的誤差（平方和）。"""
    n = b - a
    s, s2 = prefix[b] - prefix[a], prefix2[b] - prefix2[a]
    return float((s2 - s * s / n).sum())


def _best_split(cells: np.ndarray, k: int, min_len: int) -> list[int] | None:
    """把格子分成 k 段、每段至少 min_len 格、誤差最小的切法（動態規劃）。回每段的結尾。"""
    n = len(cells)
    if k * min_len > n:
        return None
    prefixes = _prefixes(cells)
    cost = [[float("inf")] * (n + 1) for _ in range(k + 1)]
    back = [[0] * (n + 1) for _ in range(k + 1)]
    cost[0][0] = 0.0
    for j in range(1, k + 1):
        for b in range(j * min_len, n + 1):
            cost[j][b], back[j][b] = _cheapest_start(cost[j - 1], prefixes, j, b, min_len)
    return _ends(back, k, n)


def _cheapest_start(prev: list[float], prefixes, j: int, b: int, min_len: int) -> tuple[float, int]:
    """第 j 段結尾在 b 時，從哪一格開始最好：(總誤差, 開始的格子)。"""
    starts = range((j - 1) * min_len, b - min_len + 1)
    return min((prev[a] + _cost(*prefixes, a, b), a) for a in starts)


def _prefixes(cells: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """累加和、平方的累加和：任何一段的誤差都可以直接算。"""
    zero = np.zeros((1, 3))
    return np.vstack([zero, np.cumsum(cells, axis=0)]), np.vstack(
        [zero, np.cumsum(cells**2, axis=0)]
    )


def _ends(back: list[list[int]], k: int, n: int) -> list[int]:
    """從動態規劃的表倒回去，找出每段的結尾。"""
    ends, b = [], n
    for j in range(k, 0, -1):
        ends.append(b)
        b = back[j][b]
    return ends[::-1]


def _distinct(cells: np.ndarray, ends: list[int]) -> bool:
    """相鄰兩段的顏色都差夠多。"""
    starts = [0, *ends[:-1]]
    means = [np.median(cells[a:b], axis=0) for a, b in zip(starts, ends, strict=True)]
    return all(np.linalg.norm(m - n) >= SPLIT for m, n in pairwise(means))


def bands(rgb: np.ndarray, height_cm: float) -> list[dict]:
    """從照片量每一段高度的顏色：[{to: 這段的頂（cm）, m: 材質, c: 顏色}]，由下往上。

    最多 4 段、每段至少全高的一成；段數取「相鄰兩段顏色都差夠多」裡最多的。
    """
    cells = _binned(_row_colours(rgb))
    min_len = max(1, int(np.ceil(MIN_BAND * len(cells))))
    ends = [len(cells)]
    for k in range(2, MAX_BANDS + 1):
        split = _best_split(cells, k, min_len)
        if split and _distinct(cells, split):
            ends = split
    starts = [0, *ends[:-1]]
    out = []
    for a, b in zip(starts, ends, strict=True):
        colour = np.round(np.median(cells[a:b], axis=0)).astype(int)
        r, g, bl = (int(v) for v in colour)
        to = round(height_cm * b / len(cells), 2)
        out.append({"to": to, "m": material(colour), "c": (r << 16) | (g << 8) | bl})
    out[-1]["to"] = height_cm
    return out


# ---------------------------------------------------------------- 燈泡
HANGING = ("pendant", "ceiling")


def light_and_beam(lathe: list[list[float]], mount: str) -> tuple[list[float], str]:
    """燈泡在中心軸上、燈罩最寬的那一層（桌燈、立燈只看上半部）。開口往下的吊燈往下照。"""
    top = max(h for _, h in lathe)
    pool = lathe if mount in HANGING else [p for p in lathe if p[1] >= top / 2]
    _, y = max(pool, key=lambda p: (p[0], -p[1]))  # 一樣寬的取比較低的
    return [0, y, 0], _beam(lathe, mount)


def _beam(lathe: list[list[float]], mount: str) -> str:
    widest = max(r for r, _ in lathe)
    bottom = min(lathe, key=lambda p: p[1])[0]
    return "down" if mount in HANGING and bottom >= OPEN_BOTTOM * widest else "all"


# ---------------------------------------------------------------- 整份
def _ok_rows(outlines_db) -> list[tuple]:
    with _open(outlines_db) as db:
        return db.execute(
            "SELECT product_id, image_url, variant_id, width_cm, height_cm, lathe FROM outline"
            " WHERE status = 'ok' ORDER BY product_id"
        ).fetchall()


def _colour_bands(photo: pathlib.Path | None, height: float) -> list[dict]:
    if photo is None or not photo.exists():
        return [{"to": height, "m": "metal", "c": GREY}]
    try:
        return bands(batch._load(photo), height)
    except ol.NoProductError:
        return [{"to": height, "m": "metal", "c": GREY}]


def _variant_name(rows: list[tuple], vid, own_photo: bool = False) -> str:
    """描的時候用的那個款式的名稱。不寫的：店家沒取名字（「標準」這種）；
    名字有顏色、而且這件商品還有別的款式（照片是商品的第一張，不一定是這個顏色）。
    """
    name = next((r[1] for r in rows if r[0] == vid), "") or ""
    others = (
        set() if own_photo else {r[1] for r in rows} - {name}
    )  # 照片就是這個款式的：顏色名可以寫
    return "" if _hidden_name(name, others) else name


def _hidden_name(name: str, others: set) -> bool:
    return name in PLACEHOLDER or bool(others and COLOUR_WORD.search(name))


def _wanted(kind: str, cat: str, model: str) -> bool:
    """這個種類要不要這件：分類對、而且燈的名字不是壁燈。"""
    if cat not in KINDS[kind]["categories"]:
        return False
    return kind != "lamps" or not batch.wall_name(model)


def _placement(kind: str, cat: str, lathe: list, height_cm: float) -> dict:
    """燈：照分類放（吊、桌、地、吸頂），加燈泡；擺飾：高的放地上、其他放桌上，不會亮。"""
    if kind == "lamps":
        light, beam = light_and_beam(lathe, cat.split("/")[1])
        return {"mount": cat.split("/")[1], "light": light, "beam": beam}
    return {"mount": "floor" if height_cm >= FLOOR_FROM_CM else "table"}


def _entry(row, product, rows, photo_for, kind: str = "lamps", own_photos=None) -> dict | None:
    pid, url, vid, width, height, lathe_json = row
    brand, model, cat = product
    lathe = json.loads(lathe_json)
    deals = offers(rows, (width, height))
    if not deals or not _wanted(kind, cat, model):
        return None
    top = max(h for _, h in lathe)
    size = _size(width, height, lathe)
    spec = KINDS[kind]
    return {
        "id": f"{spec['prefix']}{pid}",
        "brand": brand,
        "name": model,
        "variant": _variant_name(rows, vid, url in (own_photos or {}).get(vid, ())),
        "category": spec["categories"][cat],
        "size": size,
        "updated": _updated(_counted(rows, (width, height))),
        "offers": deals,
        "lathe": lathe,
        "bands": _colour_bands(photo_for(url), top),
        **_placement(kind, cat, lathe, size.get("h", size.get("hEst"))),
    }


def _size(width: float, height: float | None, lathe: list) -> dict:
    """店家沒標高度：高度是照片的比例估的，另外寫 hEst，網頁上寫「高約」（Codex 審查）。"""
    if height is not None:
        return {"w": width, "h": height}
    top, widest = max(h for _, h in lathe), 2 * max(r for r, _ in lathe)
    return {"w": width, "hEst": round(top * width / widest, 1)}  # 模型照寬度縮放，高度也跟著


def build(
    db_paths: list,
    outlines_db,
    photo_for: Callable[[str], pathlib.Path | None],
    kind: str = "lamps",
) -> dict:
    products, listings = load_products(db_paths), load_listings(db_paths)
    own = load_variant_photos(db_paths)
    have = products.keys() & listings.keys()
    entries = [
        _entry(r, products[r[0]], listings[r[0]], photo_for, kind, own)
        for r in _ok_rows(outlines_db)
        if r[0] in have
    ]
    found = list(filter(None, entries))
    return {"updated": max((e["updated"] for e in found), default=""), KINDS[kind]["key"]: found}


HEADER = """/* 自動產生，不要手改：tools/outline/export_catalog.py
 * 說明在 docs/catalog.md（燈）、docs/decor.md（花瓶、花器）
 * 爬到的商品裡，自動描「可以用」的：品牌、型號、尺寸、各家價格、輪廓、顏色（燈還有燈泡位置）。
 * 照片和照片連結都不在這裡（店家的照片只在本機）。
 */
"""


def write(data: dict, path: pathlib.Path, kind: str = "lamps") -> None:
    body = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    body = body.replace(',{"bands"', ',\n{"bands"')  # 一件一行，看 diff 比較方便
    text = (
        HEADER
        + "(function (root, data) {\n"
        + "  if (typeof module === 'object' && module.exports) module.exports = data;\n"
        + f"  else root.{KINDS[kind]['global']} = data;\n"
        + "})(typeof self !== 'undefined' ? self : this, "
        + body
        + ");\n"
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", action="append", required=True, help="softgoods 的資料庫，可以給好幾個")
    ap.add_argument("--outlines", type=pathlib.Path, default=batch.HERE / "out" / "outlines.db")
    ap.add_argument(
        "--kind", choices=sorted(KINDS), default="lamps", help="lamps 燈；decor 花瓶、花器"
    )
    ap.add_argument(
        "--out", type=pathlib.Path, help="預設：燈 prototype/catalog.js、擺飾 prototype/decor.js"
    )
    args = ap.parse_args(argv)
    cache = batch.photos.PhotoCache(batch.PHOTOS)
    data = build(args.db, args.outlines, photo_for=cache.path_for, kind=args.kind)
    out = args.out or KINDS[args.kind]["out"]
    write(data, out, kind=args.kind)
    found = data[KINDS[args.kind]["key"]]
    many = sum(len(e["offers"]) >= 2 for e in found)
    print(f"寫好 {out}：{len(found)} 件，{many} 件有兩家以上的價格")
    print(f"資料日期 {data['updated']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
