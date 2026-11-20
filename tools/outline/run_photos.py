"""拿原型的燈試自動描輪廓：描出來的形狀，跟手描的比。

    python run_photos.py <照片資料夾> <輸出資料夾>

照片資料夾裡放 <燈的 id>.jpg（原型 lamps.js 的 id）。照片是店家的，只在本機做實驗，不進 repo。
輸出：results.json（每盞的輪廓、算出來的高度、跟手描的重疊比例）、<id>_outline.png（照片上畫出描到的輪廓）、
compare.png（自動描的跟手描的並排；只有線條，沒有店家的照片）。
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

import outline as ol

ROOT = pathlib.Path(__file__).resolve().parents[2]
MAX_SIDE = 600  # 照片縮到這麼大再算（背景擴散是一圈一圈長的，太大很慢）
SUSPECT_PCT = 15  # 量出來的高度跟店家標的差超過這麼多：照片角度可能不對，要人看


def load_lamps() -> dict[str, dict]:
    """原型的燈（lamps.js 是 JavaScript，用 Node 讀）。"""
    code = "console.log(JSON.stringify(require('./prototype/lamps.js').LAMPS))"
    out = subprocess.run(
        ["node", "-e", code], cwd=ROOT, capture_output=True, check=True, text=True, encoding="utf-8"
    )
    return {lamp["id"]: lamp for lamp in json.loads(out.stdout)}


def load_photo(path: pathlib.Path) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    return np.asarray(img)


def draw_outline(rgb: np.ndarray, mask: np.ndarray, path: pathlib.Path) -> None:
    """照片上把描到的範圍塗紅、邊緣描紅線，人看得出描得對不對。"""
    img = Image.fromarray(rgb).convert("RGBA")
    tint = np.zeros((*mask.shape, 4), dtype=np.uint8)
    tint[mask] = (255, 0, 0, 70)
    edge = mask & ~np.roll(mask, 1, 0) | mask & ~np.roll(mask, 1, 1)
    tint[edge] = (255, 0, 0, 255)
    Image.alpha_composite(img, Image.fromarray(tint)).convert("RGB").save(path)


def hand_profile(lamp: dict, width_cm: float) -> ol.Profile:
    """手描的輪廓，也縮放成同樣的真實寬度，才比得了形狀。壁燈這種沒有旋轉體的回空的。"""
    prof = ol.parts_profile(lamp["parts"])
    if not prof:
        return []
    scale = width_cm / (2 * max(r for r, _ in prof))
    return [(r * scale, h * scale) for r, h in prof]


PANEL = 220  # 比較圖每一格的大小（px）


def _mirror(prof: ol.Profile, scale: float, cx: float, base: float) -> list[tuple[float, float]]:
    """側面輪廓（半邊）→ 整個剪影的多邊形：右半邊由下往上，再左半邊由上往下。"""
    right = [(cx + r * scale, base - h * scale) for r, h in prof]
    return right + [(2 * cx - x, y) for x, y in reversed(right)]


def draw_compare(rows: list[tuple[str, ol.Profile, ol.Profile]], path: pathlib.Path) -> None:
    """每盞一格：淡藍色是手描的，紅線是自動描的（都縮放成同樣的真實寬度）。"""
    sheet = Image.new("RGB", (PANEL * len(rows), PANEL + 20), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (name, hand, auto) in enumerate(rows):
        both = hand + auto
        scale = 0.85 * PANEL / max(max(h for _, h in both), 2 * max(r for r, _ in both))
        cx, base = i * PANEL + PANEL / 2, PANEL - 10
        draw.polygon(_mirror(hand, scale, cx, base), fill=(190, 215, 245))
        ring = _mirror(auto, scale, cx, base)
        draw.line([*ring, ring[0]], fill=(220, 40, 40), width=2)
        draw.text((i * PANEL + 6, PANEL + 4), name[:34], fill="black")
    sheet.save(path)


def _error_pct(measured: float, real: float | None) -> float | None:
    return round(100 * (measured - real) / real, 1) if real else None


def measure(lamp: dict, photo: pathlib.Path, out_dir: pathlib.Path) -> dict:
    rgb = load_photo(photo)
    mask = ol.foreground(rgb)
    draw_outline(rgb, mask, out_dir / f"{lamp['id']}_outline.png")
    width, height = lamp["size"]["w"], lamp["size"].get("h")
    prof = ol.profile(mask)
    width_only, auto_h = ol.to_cm(prof, width)  # 只用寬度：拿來跟手描比、檢查照片角度
    pts, _ = ol.to_cm(prof, width, height)  # 做 3D 用：寬和高都照店家標的
    simple = ol.simplify(pts, tol=0.01 * width)
    hand = hand_profile(lamp, width)
    error = _error_pct(auto_h, height)
    return {
        "id": lamp["id"],
        "category": lamp["category"],
        "real_h": height,
        "auto_h": round(auto_h, 1),
        "height_error_pct": error,
        "suspect": error is not None and abs(error) > SUSPECT_PCT,
        "overlap_with_hand": round(ol.overlap(width_only, hand), 3) if hand else None,
        "points": len(simple),
        "lathe": [[round(r, 1), round(h, 1)] for r, h in simple],
        "_hand": hand,
        "_auto": width_only,
    }


def try_measure(lamp: dict, photo: pathlib.Path, out_dir: pathlib.Path) -> dict:
    """一張照片出錯（找不到商品、檔案壞掉）只記下來，不讓整批停掉。"""
    try:
        return measure(lamp, photo, out_dir)
    except (ol.NoProductError, OSError) as e:
        return {"id": lamp["id"], "category": lamp["category"], "error": str(e), "_hand": []}


def save(results: list[dict], out_dir: pathlib.Path) -> None:
    """比較圖（只畫有手描旋轉體的），和 results.json（拿掉 _ 開頭的中間資料）。"""
    rows = [(r["id"], r["_hand"], r["_auto"]) for r in results if r.get("_hand")]
    draw_compare(rows, out_dir / "compare.png")
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    text = json.dumps(clean, ensure_ascii=False, indent=1)
    (out_dir / "results.json").write_text(text, encoding="utf-8")


def report(r: dict) -> str:
    if "error" in r:
        return f"{r['id']:28} {r['category']:4} 沒描到：{r['error']}"
    flag = "  ← 照片角度要人看" if r["suspect"] else ""
    return (
        f"{r['id']:28} {r['category']:4} 高 實際 {r['real_h']} / 描出 {r['auto_h']}"
        f"（差 {r['height_error_pct']}%）  跟手描重疊 {r['overlap_with_hand']}{flag}"
    )


def main(photo_dir: pathlib.Path, out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    lamps = load_lamps()
    photos = [p for p in sorted(photo_dir.glob("*.jpg")) if p.stem in lamps]
    results = [try_measure(lamps[p.stem], p, out_dir) for p in photos]
    save(results, out_dir)
    print("\n".join(report(r) for r in results))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]))
