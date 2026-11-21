"""從商品照生真的 3D（docs/model3d.md）：照片 → 去背 → TripoSG 生形狀 → 轉正 → 存 GLB。

    python make3d.py --groups sofa,chair,table --limit 50

結果：prototype/models3d/<檔名>.glb（只有形狀和照片座標，沒有照片）和 index.json。
做不出來的記在 tools/model3d/out/skipped.json（不上網站），下次不再試。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from collections.abc import Callable

import numpy as np

import glb
import shape

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GOODS = ROOT / "prototype" / "goods"
OUT = ROOT / "prototype" / "models3d"
SKIPPED = HERE / "out" / "skipped.json"
CUTOUT = HERE / "cutout_cli.js"
MAX_SIDE = 800  # 照片縮到這麼大再去背（跟網頁一樣）
FACES = 10_000  # 形狀減到大約這麼多面（手機跑得動、一件一兩百 KB）
# 從正面看的輪廓跟照片重疊不到這麼多：形狀不像，不用（細框的椅子多半在 0.62 上下，做出來很亂）
MIN_SCORE = 0.65
SEED = 42
# 形狀格子：2^8 = 256 一邊。2^9 慢三成、看起來一樣（反正會減到一萬個面；docs/model3d.md 結果）
OCTREE_DEPTH = 8
DEFAULT_GROUPS = "sofa,chair,table,storage,bed,outdoor,furniture,lamp-floor"

Fetch = Callable[[str], "np.ndarray | None"]  # 照片網址 → RGB（縮過的）；讀不到回 None
Cut = Callable[[np.ndarray, bool], tuple]  # (RGB, 吊燈可以碰到上面) → ({ok, reason, box}, 透明度)
Ai = Callable[[np.ndarray], tuple]  # 給模型的正方形照片 → (點, 面)


# ---------------------------------------------------------------- 先做哪些
def _stores(item: dict) -> int:
    return len({o["store"] for o in item["sizes"][0]["offers"]})


def order(groups: dict[str, list[dict]]) -> list[dict]:
    """每一類照「幾家店有賣」排（越多越常見）；各類輪流，前面幾十件就各類都有。"""
    ranked = [sorted(items, key=lambda i: (-_stores(i), i["id"])) for items in groups.values()]
    out = []
    for k in range(max((len(r) for r in ranked), default=0)):
        out += [r[k] for r in ranked if k < len(r)]
    return out


# ---------------------------------------------------------------- 一件
def choose_photo(item: dict, fetch: Fetch, cut: Cut):
    """第一個尺寸的照片裡，第一張去背成功的：(網址, RGB, 透明度, 商品範圍, 第幾張)。

    都不行回原因：讀得到但都不能去背 "photo"（不適合，不再試）；一張都讀不到 "fetch"（下次再試）。
    """
    size, reason = item["sizes"][0], "fetch"
    for k, url in enumerate(size["photos"]):
        rgb = fetch(url)
        if rgb is None:
            continue
        reason = "photo"
        result, alpha = cut(rgb, size["mount"] == "ceiling")
        if result["ok"]:
            return url, rgb, alpha, result["box"], k
    return reason


def make_one(item: dict, ai: Ai, fetch: Fetch, cut: Cut) -> tuple[bytes | None, dict]:
    """一件商品 → (GLB, 說明)；做不出來回 (None, {"skip": 原因})。"""
    chosen = choose_photo(item, fetch, cut)
    if isinstance(chosen, str):
        return None, {"skip": chosen}
    url, rgb, alpha, box_px, k = chosen
    v, f = ai(shape.model_input(rgb, alpha))
    v, score = shape.orient(np.asarray(v, dtype=np.float32), np.asarray(f), alpha)
    if score < MIN_SCORE:
        return None, {"skip": "shape", "score": round(score, 3)}
    v = shape.place(v)
    h, w = alpha.shape
    data = glb.encode(v, f, shape.photo_uv(v, box_px, (w, h)))
    extent = (v.max(axis=0) - v.min(axis=0)).round(5).tolist()
    meta = {
        "photo": url,
        "photoIndex": k,  # 網頁用：這個尺寸同一個位置是這張照片，才是同一款（Codex 審查）
        "box": [int(b) for b in box_px],
        "wh": [w, h],
        "extent": extent,
        "score": round(score, 3),
    }
    return data, meta


# ---------------------------------------------------------------- 存檔
def file_name(goods_id: str) -> str:
    """商品 id 有中文和冒號：檔名用它的雜湊。"""
    return hashlib.sha1(goods_id.encode("utf-8")).hexdigest()[:16] + ".glb"


def _read_json(path: pathlib.Path, empty):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty


def load_skipped(path: pathlib.Path) -> dict:
    return _read_json(path, {})


def _write_json(path: pathlib.Path, data) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    _write_whole(path, text.encode("utf-8"))


def _write_whole(path: pathlib.Path, data: bytes) -> None:
    """先寫暫存檔再換過去：中途停掉不會留下寫一半的檔案（Codex 審查）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def run(items, ai: Ai, fetch: Fetch, cut: Cut, out=OUT, skipped=SKIPPED, limit=None) -> int:
    """照順序做；做過的、不適合的不再做（照片換了就重做）；每做完一件就存。

    limit：這次最多「試」幾件（成功、不成功都算，不會一路試幾千件）。回做成了幾件。
    """
    out, skipped = pathlib.Path(out), pathlib.Path(skipped)
    index = _read_json(out / "index.json", {"models": {}})
    skip = load_skipped(skipped)
    todo = _todo(items, index["models"], skip)[:limit]
    made = sum(_make_and_save(i, (ai, fetch, cut), (out, index), (skipped, skip)) for i in todo)
    _write_json(out / "index.json", index)  # 一件都沒做也要有（網頁會讀）
    return made


def _photos_of(item: dict) -> list[str]:
    return item["sizes"][0]["photos"]


def _fresh(item: dict, done: dict, skip: dict) -> bool:
    """要不要做：沒做過；做過但那張照片不在了（重新爬過）；不適合過但照片換了。"""
    if item["id"] in done:
        return done[item["id"]]["photo"] not in _photos_of(item)
    passed = skip.get(item["id"])
    return passed is None or passed["photos"] != _photos_of(item)


def _todo(items, done: dict, skip: dict) -> list[dict]:
    return [i for i in items if _fresh(i, done, skip)]


def _make_and_save(item: dict, tools: tuple, site: tuple, local: tuple) -> int:
    """做一件；成功存 GLB 和 index（回 1）；不適合記在 skipped，讀不到不記（回 0）。"""
    (out, index), (skipped, skip) = site, local
    data, meta = make_one(item, *tools)
    if data is None:
        if meta["skip"] != "fetch":
            skip[item["id"]] = {"reason": meta["skip"], "photos": _photos_of(item)}
            _write_json(skipped, skip)
        return 0
    name = file_name(item["id"])
    _write_whole(out / name, data)
    index["models"][item["id"]] = {"file": name, **meta}
    _write_json(out / "index.json", index)
    kb, score = len(data) // 1024, meta["score"]
    print(
        f"{len(index['models'])}. {item['brand']} {item['name']}：{kb} KB，重疊 {score}", flush=True
    )
    return 1


# ---------------------------------------------------------------- 真的照片、真的 AI
def node_cut(rgb: np.ndarray, allow_top: bool):
    """用網頁同一份去背（prototype/cutout.js）。"""
    h, w = rgb.shape[:2]
    rgba = np.dstack([rgb, np.full((h, w), 255, dtype=np.uint8)])
    with tempfile.TemporaryDirectory() as tmp:
        raw = pathlib.Path(tmp) / "photo.rgba"
        raw.write_bytes(rgba.tobytes())
        cmd = ["node", str(CUTOUT), str(raw), str(w), str(h), "1" if allow_top else "0"]
        result = json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)
        alpha_file = raw.with_name(raw.name + ".alpha")
        alpha = (
            np.frombuffer(alpha_file.read_bytes(), dtype=np.uint8).reshape(h, w)
            if result["ok"]
            else None
        )
    return result, alpha


def photo_fetcher() -> Fetch:  # pragma: no cover - 連網路
    """照片：用描輪廓那邊的快取（守 robots、每個網站至少隔一秒），縮到 800 px。"""
    sys.path.insert(0, str(ROOT / "tools" / "outline"))
    import batch
    import photos
    from PIL import Image

    cache = photos.PhotoCache(batch.PHOTOS)

    def fetch(url: str):
        local = cache.get(url)
        if not local:
            return None
        try:
            img = Image.open(local).convert("RGB")
        except OSError:
            return None
        k = min(1.0, MAX_SIDE / max(img.size))
        return np.asarray(img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS))

    return fetch


class TripoSG:  # pragma: no cover - 要顯示卡
    """TripoSG（VAST，MIT）：tools/model3d/vendor/TripoSG 的程式、Hugging Face 快取裡的模型。"""

    def __init__(self, steps: int = 50):
        import types

        sys.path.insert(0, str(HERE / "vendor" / "TripoSG"))
        sys.modules.setdefault(
            "diso", types.SimpleNamespace(DiffDMC=None)
        )  # 只有快速解碼用到，我們不用
        import torch
        from huggingface_hub import snapshot_download
        from triposg.pipelines.pipeline_triposg import TripoSGPipeline

        self.torch, self.steps = torch, steps
        folder = snapshot_download("VAST-AI/TripoSG", local_files_only=True)
        self.pipe = TripoSGPipeline.from_pretrained(folder).to("cuda", torch.float16)

    def __call__(self, image: np.ndarray):
        from PIL import Image

        out = self.pipe(
            image=Image.fromarray(image),
            generator=self.torch.Generator(device="cuda").manual_seed(SEED),
            num_inference_steps=self.steps,
            guidance_scale=7.0,
            use_flash_decoder=False,  # 另一條要編譯的 diso；這條用 skimage
            hierarchical_octree_depth=OCTREE_DEPTH,
        ).samples[0]
        return simplify(out[0], out[1])


def simplify(v, f, faces: int = FACES):  # pragma: no cover - pymeshlab
    """合併重複的點、拿掉飄在旁邊的小碎塊、減到大約 faces 個面。"""
    import pymeshlab

    ms = pymeshlab.MeshSet()
    ms.add_mesh(
        pymeshlab.Mesh(
            vertex_matrix=np.asarray(v, dtype=np.float64), face_matrix=np.asarray(f, dtype=np.int32)
        )
    )
    ms.meshing_merge_close_vertices()
    ms.meshing_remove_connected_component_by_diameter(mincomponentdiag=pymeshlab.PercentageValue(5))
    ms.meshing_decimation_quadric_edge_collapse(targetfacenum=faces, preservenormal=True)
    m = ms.current_mesh()
    return m.vertex_matrix().astype(np.float32), m.face_matrix().astype(np.int64)


def load_groups(keys: list[str]) -> dict[str, list[dict]]:
    return {k: json.loads((GOODS / f"{k}.json").read_text(encoding="utf-8"))["items"] for k in keys}


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - 要顯示卡
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--groups", default=DEFAULT_GROUPS, help="goods 的種類，逗號分開")
    ap.add_argument("--limit", type=int, default=None, help="這次最多做幾件")
    ap.add_argument("--steps", type=int, default=50)
    args = ap.parse_args(argv)
    items = order(load_groups(args.groups.split(",")))
    made = run(items, TripoSG(args.steps), photo_fetcher(), node_cut, limit=args.limit)
    print(f"這次做了 {made} 件")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
