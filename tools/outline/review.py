"""抽查圖：隨機抽幾件「可以用」的，給人看描得對不對（docs/outline.md「批次」第 14 句）。

每一件一格：左邊是照片（紅線是程式當成商品的範圍），右邊是描出來的形狀（轉一圈前的剪影）。
照片是店家的，圖只存在本機 out/，不進 repo。
"""

from __future__ import annotations

import json
import pathlib
import random
from collections.abc import Callable

import numpy as np
from PIL import Image, ImageDraw

import outline as ol

PANEL = 200  # 每一格裡的照片、形狀各多大（px）
COLUMNS = 4
LABEL = 18


def _photo_panel(path: pathlib.Path) -> Image.Image:
    img = Image.open(path)
    img = img.convert("RGBA" if "A" in img.getbands() else "RGB").convert("RGBA")
    img.thumbnail((PANEL, PANEL))
    mask = ol.foreground(np.asarray(img))
    edge = mask & ~np.roll(mask, 1, 0) | mask & ~np.roll(mask, 1, 1)
    tint = np.zeros((*mask.shape, 4), dtype=np.uint8)
    tint[edge] = (230, 30, 30, 255)
    out = Image.new("RGB", (PANEL, PANEL), "white")
    shown = Image.alpha_composite(Image.new("RGBA", img.size, "white"), img)
    shown = Image.alpha_composite(shown, Image.fromarray(tint))
    out.paste(shown.convert("RGB"), ((PANEL - img.width) // 2, (PANEL - img.height) // 2))
    return out


def _shape_panel(lathe: list[list[float]]) -> Image.Image:
    """[[半徑, 高], ...] 左右鏡射成剪影，縮放到格子裡。"""
    out = Image.new("RGB", (PANEL, PANEL), "white")
    tallest = max(h for _, h in lathe)
    widest = max(r for r, _ in lathe)
    scale = 0.9 * PANEL / max(tallest, 2 * widest, 1e-6)
    cx, base = PANEL / 2, PANEL - 0.05 * PANEL
    right = [(cx + r * scale, base - h * scale) for r, h in lathe]
    ImageDraw.Draw(out).polygon(
        right + [(2 * cx - x, y) for x, y in reversed(right)], fill=(110, 110, 120)
    )
    return out


def sheet(
    results,
    photo_path: Callable[[str], pathlib.Path] | object,
    path: pathlib.Path,
    n: int = 40,
    seed: int = 0,
) -> pathlib.Path:
    """抽 n 件 status = ok 的畫成一張圖。photo_path：照片網址 → 本機檔案（PhotoCache 也可以）。"""
    find = getattr(photo_path, "path_for", photo_path)
    rows = results.db.execute(
        "SELECT product_id, image_url, lathe FROM outline WHERE status = 'ok' ORDER BY product_id"
    ).fetchall()
    rows = [r for r in rows if find(r[1]).exists()]
    picked = random.Random(seed).sample(rows, min(n, len(rows)))
    cols = max(1, min(COLUMNS, len(picked)))
    cell_w, cell_h = 2 * PANEL, PANEL + LABEL
    img = Image.new("RGB", (cols * cell_w, max(1, -(-len(picked) // cols)) * cell_h), "white")
    draw = ImageDraw.Draw(img)
    for i, (pid, url, lathe) in enumerate(picked):
        x, y = (i % cols) * cell_w, (i // cols) * cell_h
        img.paste(_photo_panel(find(url)), (x, y))
        img.paste(_shape_panel(json.loads(lathe)), (x + PANEL, y))
        draw.text((x + 4, y + PANEL + 2), pid[:52], fill="black")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path
