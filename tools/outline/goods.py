"""爬到的全部商品（地毯以外）→ prototype/goods/：一類一個 JSON，用到才讀。說明在 docs/goods.md。

每件商品：品牌、型號、每個尺寸各自的各家價格、最多 4 張照片網址、
預設放法（地上、桌上、牆上、天花板）。
照片不下載：去背在瀏覽器裡做（prototype/cutout.js），這裡只排「先試哪一張」。

    python goods.py --db ../softgoods/softgoods.db
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from dataclasses import dataclass

import export_catalog as ex
import rugs

OUT = rugs.OUT.parent / "goods"
MAX_PHOTOS = 4
TALL_FLOOR_CM = 70  # 擺飾類高過這個放地上
MIRROR_FLOOR_CM = 140  # 鏡子高過這個靠在地上
WALL_WORDS = re.compile(r"壁|掛|wall")  # 名字寫明掛牆的鏡子，再大也掛牆

Size = tuple[float, float, float]  # 寬、深、高 cm


@dataclass(frozen=True)
class Group:
    label: str
    mount: str  # floor 地上、table 桌上、wall 牆上、ceiling 天花板
    size: Size  # 沒標尺寸時用的一般大小（寬、深、高 cm）
    cats: tuple = ()  # 爬蟲的分類 (cat1, cat2)


# 順序就是選單的順序
GROUPS: dict[str, Group] = {
    "sofa": Group("沙發", "floor", (200, 90, 80), (("furniture", "sofa"),)),
    "chair": Group("椅子、凳子", "floor", (55, 55, 80), (("furniture", "chair"),)),
    "table": Group("桌子", "floor", (120, 70, 75), (("furniture", "table"),)),
    "storage": Group("櫃子、收納", "floor", (100, 40, 80), (("furniture", "storage"),)),
    "bed": Group("床", "floor", (160, 200, 40), (("furniture", "bed"),)),
    "outdoor": Group("戶外家具", "floor", (60, 60, 80), (("furniture", "outdoor"),)),
    "furniture": Group("其他家具", "floor", (80, 40, 80), (("furniture", None),)),
    "lamp-pendant": Group("吊燈", "ceiling", (40, 40, 40), (("lighting", "pendant"),)),
    "lamp-ceiling": Group("吸頂燈", "ceiling", (40, 40, 15), (("lighting", "ceiling"),)),
    "lamp-table": Group("桌燈", "table", (25, 25, 45), (("lighting", "table"),)),
    "lamp-floor": Group("立燈", "floor", (40, 40, 160), (("lighting", "floor"),)),
    "lamp-wall": Group("壁燈", "wall", (20, 20, 30), (("lighting", "wall"),)),
    "lamp-other": Group(
        "其他燈、燈泡",
        "table",
        (20, 20, 30),
        (("lighting", "bulb"), ("lighting", "outdoor"), ("lighting", "track"), ("lighting", None)),
    ),
    "cushion": Group("抱枕", "table", (45, 15, 45), (("textile", "cushion"),)),
    "throw": Group(
        "毯子、布",
        "table",
        (40, 30, 10),
        (
            ("textile", "throw"),
            ("textile", "fabric"),
            ("textile", "table"),
            ("textile", "curtain"),
            ("textile", None),
        ),
    ),
    "bedding": Group("寢具", "table", (50, 40, 15), (("textile", "bedding"),)),
    "bath": Group("浴室織品", "table", (40, 30, 10), (("textile", "bath"),)),
    "vase": Group("花瓶", "table", (20, 20, 30), (("decor", "vase"),)),
    "planter": Group(
        "盆器、植物", "table", (30, 30, 30), (("greenery", "planter"), ("greenery", "live"))
    ),
    "sculpture": Group("雕塑、擺件", "table", (20, 20, 25), (("decor", "sculpture"),)),
    "scent": Group("香氛、蠟燭", "table", (10, 10, 12), (("decor", "scent"),)),
    "tray": Group("托盤", "table", (40, 25, 4), (("decor", "tray"),)),
    "decor": Group("其他擺飾", "table", (20, 20, 20), (("decor", None),)),
    "clock": Group("時鐘", "wall", (30, 5, 30), (("decor", "clock"),)),
    "mirror": Group("鏡子", "wall", (60, 3, 80), (("decor", "mirror"),)),
    "wall": Group("牆面裝飾", "wall", (50, 3, 50), (("decor", "wall_decor"),)),
    "art": Group(
        "畫、海報、框",
        "wall",
        (50, 3, 70),
        (("art", "print"), ("art", "frame"), ("art", "painting"), ("art", None)),
    ),
    "other": Group("其他小物（沒分類）", "table", (15, 15, 15)),
}
BY_CAT = {cat: key for key, g in GROUPS.items() for cat in g.cats}
NOT_HERE = {("textile", "rug")}  # 地毯有自己的卡片（rugs.py）
TALL_TO_FLOOR = {"vase", "planter", "sculpture", "decor", "other", "lamp-other"}
FURNITURE = {"sofa", "chair", "table", "storage", "bed", "outdoor", "furniture"}
MIN_FURNITURE_SHARE = 0.2  # 家具最長的邊不到一般大小的兩成：單位錯了
MIN_SIDE_SHARE = 0.1  # 家具每一邊至少要有一般最短邊的一成（寬 0.8 cm 的沙發不可能）
MAX_SHARE = 5  # 家具最長的邊超過一般最長邊的五倍：也是錯的
# 爬到的分類太籠統（只寫「家具」「燈」「擺飾」）：名稱看得出來就照名稱分
GENERIC = {
    ("furniture", None),
    ("lighting", None),
    ("decor", None),
    ("textile", None),
    ("art", None),
}

# 沒分類的用名稱裡的字分：先比長的（「桌燈」要先於「燈」「桌」，「桌鏡」要先於「桌」）
NAME_RULES: list[tuple[str, str]] = [
    (r"吊燈|pendant", "lamp-pendant"),
    (r"吸頂燈", "lamp-ceiling"),
    (r"桌燈|檯燈|台燈|table lamp|desk lamp", "lamp-table"),
    (r"立燈|落地燈|floor lamp", "lamp-floor"),
    (r"壁燈|wall lamp|sconce", "lamp-wall"),
    (r"燈|\blamp\b", "lamp-other"),
    (r"鏡", "mirror"),
    (r"sofa table|coffee table|side table|邊桌|茶几", "table"),
    (r"沙發|sofa", "sofa"),
    (r"椅|凳|chair|stool", "chair"),
    (r"櫃|層架|收納架|書架|shelf|shelving|cabinet|dresser", "storage"),
    (r"床(?!單|包|墊)", "bed"),
    (r"屏風", "furniture"),
    (r"桌|table|desk", "table"),
    (r"抱枕|靠墊|cushion", "cushion"),
    (r"毯|blanket|throw", "throw"),
    (r"花瓶|花器|vase", "vase"),
    (r"盆栽|植栽|盆器|planter", "planter"),
    (r"蠟燭|香氛|擴香|candle", "scent"),
    (r"時鐘|掛鐘|clock", "clock"),
    (r"托盤|tray", "tray"),
    (r"海報|掛畫|畫框|相框|poster|print", "art"),
]


def group_of(cat1: str | None, cat2: str | None, name: str) -> str | None:
    """商品放哪一類；地毯回 None（不放這裡）。分類籠統或沒分類的，先看名稱。"""
    cat = (cat1, cat2)
    if cat in NOT_HERE:
        return None
    named = _by_name(name)
    if cat in BY_CAT and (cat not in GENERIC or named is None):
        return BY_CAT[cat]
    return named or "other"


def _by_name(name: str) -> str | None:
    low = (name or "").lower()
    return next((g for pattern, g in NAME_RULES if re.search(pattern, low)), None)


def mount_of(group: str, size: dict, name: str = "") -> str:
    """預設放法：照種類；擺飾類太高放地上，大鏡子靠在地上（名字寫明「壁鏡」的還是掛牆）。"""
    h = size["h"]
    if group in TALL_TO_FLOOR and h >= TALL_FLOOR_CM:
        return "floor"
    if group == "mirror" and h >= MIRROR_FLOOR_CM and not WALL_WORDS.search(name.lower()):
        return "floor"
    return GROUPS[group].mount


# ---------------------------------------------------------------- 資料庫
_ROWS = """
SELECT p.product_id, b.name, p.model, p.cat1, p.cat2,
       v.variant_id, v.name, v.width_mm, v.depth_mm, v.height_mm, v.diameter_mm, v.pack,
       s.name, l.price, l.in_stock, l.url, l.gone_at, l.last_seen_at
FROM product p JOIN brand b ON b.brand_id = p.brand_id
JOIN variant v ON v.product_id = p.product_id
LEFT JOIN listing l ON l.variant_id = v.variant_id
LEFT JOIN site s ON s.site_id = l.site_id
ORDER BY p.product_id, v.variant_id
"""
_PHOTOS = """
SELECT product_id, variant_id, src_url FROM image ORDER BY product_id, position, image_id
"""


def _read(db_path) -> tuple[list, list]:
    with rugs._open(db_path) as db:
        return db.execute(_ROWS).fetchall(), db.execute(_PHOTOS).fetchall()


def _cm(mm) -> float | None:
    return round(mm / 10, 1) if mm else None


def size_of(row, group: str | None = None) -> Size | None:
    """一列（variant_id, 名稱, 寬, 深, 高, 直徑, ...）mm → (寬, 深, 高) cm；有直徑就當寬和深。

    給了種類的話，不可能的尺寸（家具小過一般的兩成，爬到的單位錯了）當成沒標。
    """
    size = _dims(row)
    return size if size and _plausible(size, group) else None


def _dims(row) -> Size | None:
    w, d, h, dia = (_cm(v) for v in row[2:6])
    w, d = (w or dia), (d or dia)
    return (w, d, h) if (w or h) else None


def _plausible(size: Size, group: str | None) -> bool:
    """家具的尺寸要合理：最長的邊在一般的兩成到五倍之間，每一邊至少一般最短邊的一成。"""
    if group not in FURNITURE:
        return True
    ordinary, sides = GROUPS[group].size, [v for v in size if v]
    longest_ok = MIN_FURNITURE_SHARE * max(ordinary) <= max(sides) <= MAX_SHARE * max(ordinary)
    return longest_ok and min(sides) >= MIN_SIDE_SHARE * min(ordinary)


def _full(size: Size, group: str) -> Size:
    """缺的邊用那一類一般大小的比例補（寬 120 的桌子沒標高：高 = 120 x 75/120）；最少 0.1 cm。"""
    ordinary = GROUPS[group].size
    w, _, h = size
    base = (w / ordinary[0]) if w else (h / ordinary[2])
    return tuple(v or max(0.1, round(g * base, 1)) for v, g in zip(size, ordinary, strict=True))


def _sizes(rows: list[tuple], group: str) -> list[dict]:
    """每個尺寸一列、各自的各家價格；都沒尺寸就用一般大小（guess）。沒有價格的尺寸不放。"""
    known = _known(rows, group)
    if not known:
        return _guessed(rows, group)
    found = (_one_size(rows, size, len(known) == 1, group) for size in known)
    return [s for s in found if s]


def _known(rows: list[tuple], group: str) -> list[Size]:
    """有價格的款式標了的尺寸，由小排到大（沒標的邊當 0）。

    沒價格的款式的尺寸不算：不然有價格、沒尺寸的款式兩邊都算不進去，整件消失（Codex 審查）。
    """
    return sorted({s for r in rows if ex._usable(r) and (s := size_of(r, group))}, key=_order)


def _order(size: Size) -> list[float]:
    return [v or 0 for v in size]


def _guessed(rows: list[tuple], group: str) -> list[dict]:
    usable = [r for r in rows if ex._usable(r)]
    deals = rugs._cheapest(usable)
    if not deals:
        return []
    w, d, h = GROUPS[group].size
    return [{"w": w, "d": d, "h": h, "guess": True, "offers": deals, "seen": rugs._seen(usable)}]


def _one_size(rows: list[tuple], size: Size, single: bool, group: str) -> dict | None:
    counted = [r for r in rows if _counts(r, size, single, group)]
    deals = rugs._cheapest(counted)
    if not deals:
        return None
    w, d, h = _full(size, group)
    out = {"w": w, "d": d, "h": h, "offers": deals, "seen": rugs._seen(counted), "key": size}
    est = _estimated(size)
    return {**out, "est": est} if est else out


def _estimated(size: Size) -> list[str]:
    """照一般比例補的邊（店家沒標）：網頁不拿來算大小。"""
    return [k for k, v in zip("wdh", size, strict=True) if not v]


def _counts(row, size: Size, single: bool, group: str) -> bool:
    """算不算這個尺寸的價格：同尺寸；只有一個尺寸時，沒標尺寸的也算。"""
    mine = size_of(row, group)
    return (mine == size or (single and mine is None)) and ex._usable(row)


def _photos(rows: list[tuple], pics: list[tuple], mine) -> list[str]:
    """mine(列) 是 True 的款式自己的照片排前面，再來是商品的照片（照位置），不重複，最多 4 張。"""
    own = _own(rows, pics, mine)
    ordered = dict.fromkeys(own + [url for _, url in pics])
    return [u for u in ordered if ex._web_link(u)][:MAX_PHOTOS]


def _own(rows: list[tuple], pics: list[tuple], mine) -> list[str]:
    ids = {r[0] for r in rows if mine(r)}
    return [url for vid, url in pics if vid in ids]


def _size_photos(rows: list[tuple], pics: list[tuple], size: dict, group: str) -> list[str]:
    """這個尺寸的款式自己的照片先（小的紅椅子、大的藍椅子）；猜的尺寸：有尺寸的款式先。"""
    key = size.get("key")
    if key is None:
        return _photos(rows, pics, size_of)
    return _photos(rows, pics, lambda r: size_of(r, group) == key)


def _product(prows: list[tuple], pics: list[tuple]) -> dict | None:
    brand, model, cat1, cat2 = prows[0][:4]
    group = group_of(cat1, cat2, model)
    if group is None:
        return None
    # (variant_id, 名稱, 寬, 深, 高, 直徑, 幾件一組, 店, 價格, ...)
    variant_rows = [r[4:] for r in prows]
    sizes = _sizes(variant_rows, group)
    if not sizes:
        return None
    for size in sizes:  # 每個尺寸自己的照片、自己的放法（80 cm 的鏡子掛牆、160 cm 的靠地上）
        size["photos"] = _size_photos(variant_rows, pics, size, group)
        size["mount"] = mount_of(group, size, model)
    return {
        "group": group,
        "brand": brand,
        "name": model,
        "sizes": sizes,
        "mount": sizes[0]["mount"],
    }


def load(*db_paths) -> dict[str, dict]:
    """商品 id → 種類、品牌、型號、尺寸（各自的價格）、照片網址、放法。沒有價格的不放。"""
    rows, pics = _read_all(db_paths)
    by_pid, pics_of = rugs._group(rows), rugs._group(pics)
    found = {}
    for pid, prows in by_pid.items():
        item = _product(prows, pics_of.get(pid, []))
        if item:
            found[pid] = item
    return found


def _read_all(db_paths) -> tuple[list, list]:
    rows, pics = [], []
    for path in db_paths:
        more_rows, more_pics = _read(path)
        rows += more_rows
        pics += more_pics
    return rows, pics


# ---------------------------------------------------------------- 整份
def _item(pid: str, p: dict) -> dict:
    sizes = [{k: v for k, v in s.items() if k not in ("seen", "key")} for s in p["sizes"]]
    seen = [s["seen"] for s in p["sizes"] if s.get("seen")]
    return {
        "id": f"g:{pid}",
        "brand": p["brand"],
        "name": p["name"],
        "mount": p["mount"],
        "sizes": sizes,
        "updated": max(seen, default=""),
    }


def build(db_paths: list) -> dict[str, list[dict]]:
    """種類 → 商品（照品牌、型號排）。"""
    out: dict[str, list[dict]] = {}
    for pid, p in load(*db_paths).items():
        out.setdefault(p["group"], []).append(_item(pid, p))
    for items in out.values():
        items.sort(key=lambda i: (i["brand"].lower(), i["name"].lower(), i["id"]))
    return {key: out[key] for key in GROUPS if key in out}


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def write(groups: dict[str, list[dict]], out: pathlib.Path) -> None:
    """out/index.json（有哪些種類、幾件）和 out/<種類>.json（一件一行，改了好比對）。

    舊的種類檔先刪掉。
    """
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    index = [
        {"key": key, "label": GROUPS[key].label, "count": len(items)}
        for key, items in groups.items()
    ]
    (out / "index.json").write_text(_dump({"groups": index}) + "\n", encoding="utf-8", newline="\n")
    for key, items in groups.items():
        body = ",\n".join(_dump(i) for i in items)
        text = '{"items":[\n' + body + "\n]}\n"
        (out / f"{key}.json").write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", action="append", required=True, help="softgoods 的資料庫，可以給好幾個")
    ap.add_argument("--out", type=pathlib.Path, default=OUT)
    args = ap.parse_args(argv)
    groups = build(args.db)
    write(groups, args.out)
    total = sum(len(v) for v in groups.values())
    print(f"寫好 {args.out}：{len(groups)} 類、{total} 件")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
