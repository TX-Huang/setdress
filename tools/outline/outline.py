"""從商品照片描出側面輪廓，轉成原型用的旋轉體（lathe）。

沒有原廠 3D 模型時的替代（2026-11-20 Isaac：「沒有提供 3D 模型的情況下可以先這樣用」）：
大部分的燈、花瓶、圓桌是「一條側面輪廓繞中心轉一圈」，原型 14 盞燈就是手描輪廓做的。
這裡把手描換成自動：

  1. 背景：照片邊框的顏色，從邊框往裡長，長得到的同色區就是背景（白燈罩拍在白底上，
     只要邊緣有一圈淡灰，圈裡面的白就不會被當成背景）
  2. 前景：不是背景的，留最大的那一塊（角落的貼紙、標籤丟掉）
  3. 中心軸：每一列中點的中位數。每一列的半寬取「離中心軸比較近的那一邊」——
     商品照的影子常落在一邊（JWDA、Carrie），取窄的那邊就不會把影子量進去
  4. 吊燈頂端的電線：前景碰到照片頂端、而且很細的那幾列剪掉
  5. 用真實寬度（直徑）換成公分；高度是算出來的，拿來跟商品標的高度對答案
  6. 點太多就簡化（Douglas-Peucker），變成原型 lamps.js 的 [[半徑, 高], ...]

只用 numpy、Pillow，不用 AI 模型。限制：只適合「轉一圈」的形狀；照片要是側面、背景要單色。
"""

from __future__ import annotations

from collections import deque
from itertools import pairwise

import numpy as np

BG_TOL = 12.0  # 跟背景色差多少以內算背景（RGB 距離）
CORD_FRAC = 0.06  # 頂端比最寬處窄這麼多的，當成電線

CORD_WOBBLE = 2  # 電線一路跟最上面一樣細：寬度最多多這麼多 px
CORD_MIN_SHARE = 0.05  # 而且要夠長（佔整個高度這麼多以上）；尖頂只會細短短幾列
BORDER_SHARE = 0.1  # 邊框上佔這麼多以上的顏色，都算背景色（白牆加灰地板這種）
UPPER_SHARE = 0.5  # 中心軸只看上面這一半：影子落在底部


class NoProductError(ValueError):
    """照片裡找不到商品（整張都是背景，或描出來寬度是 0）。"""


Cm = float | None  # 店家標的尺寸，可能沒標
Profile = list[tuple[float, float]]  # [(半徑 cm, 高 cm), ...]，跟原型 lamps.js 的 lathe pts 一樣
PixelProfile = list[tuple[int, float]]  # [(從最低點算的高 px, 半寬 px), ...]


# ------------------------------------------------------------ 前景


def _border_colours(rgb: np.ndarray) -> list[np.ndarray]:
    """邊框上常見的顏色（佔邊框一成以上的），每一種都算背景色；都不夠多就用中位數。"""
    edge = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]).astype(float)
    bins = (edge // 16).astype(int) @ np.array([256 * 256, 256, 1])
    values, counts = np.unique(bins, return_counts=True)
    common = values[counts >= BORDER_SHARE * len(edge)]
    colours = [edge[bins == v].mean(axis=0) for v in common]
    return colours or [np.median(edge, axis=0)]


def _as_rgba(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """灰階、RGB、RGBA 都收。回 (RGB, 透明的地方)。"""
    if img.ndim == 2:
        img = np.dstack([img] * 3)
    clear = img[..., 3] < 128 if img.shape[2] == 4 else np.zeros(img.shape[:2], dtype=bool)
    return img[..., :3], clear


def _grow(seed: np.ndarray, allowed: np.ndarray) -> np.ndarray:
    """從 seed 往上下左右長，只長在 allowed 裡，長到不能再長。"""
    cur = seed & allowed
    while True:
        nxt = cur.copy()
        nxt[1:] |= cur[:-1]
        nxt[:-1] |= cur[1:]
        nxt[:, 1:] |= cur[:, :-1]
        nxt[:, :-1] |= cur[:, 1:]
        nxt &= allowed
        if np.array_equal(nxt, cur):
            return cur
        cur = nxt


def background_mask(img: np.ndarray, tol: float = BG_TOL) -> np.ndarray:
    """跟邊框常見顏色像的、從邊框長得到的；透明的地方一定是背景。"""
    rgb, clear = _as_rgba(img)
    pixels = rgb.astype(float)
    near = [np.linalg.norm(pixels - c, axis=2) <= tol for c in _border_colours(rgb)]
    similar = clear | np.any(near, axis=0)
    border = np.zeros(similar.shape, dtype=bool)
    border[0], border[-1], border[:, 0], border[:, -1] = True, True, True, True
    return _grow(border, similar)


def _neighbours(y: int, x: int, shape: tuple[int, int]):
    h, w = shape
    for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
        if 0 <= ny < h and 0 <= nx < w:
            yield ny, nx


def _component(mask: np.ndarray, start: tuple[int, int], seen: np.ndarray) -> list[tuple[int, int]]:
    """從 start 開始，連在一起的那一塊（上下左右相連）。"""
    todo, pixels = deque([start]), []
    seen[start] = True
    while todo:
        y, x = todo.popleft()
        pixels.append((y, x))
        for n in _neighbours(y, x, mask.shape):
            if mask[n] and not seen[n]:
                seen[n] = True
                todo.append(n)
    return pixels


def largest_piece(mask: np.ndarray) -> np.ndarray:
    seen = np.zeros(mask.shape, dtype=bool)
    best: list[tuple[int, int]] = []
    for y, x in zip(*np.nonzero(mask), strict=True):
        if not seen[y, x]:
            piece = _component(mask, (int(y), int(x)), seen)
            best = piece if len(piece) > len(best) else best
    out = np.zeros(mask.shape, dtype=bool)
    if best:
        ys, xs = zip(*best, strict=True)
        out[list(ys), list(xs)] = True
    return out


def foreground(rgb: np.ndarray, tol: float = BG_TOL) -> np.ndarray:
    """商品本身：不是背景的地方，最大的那一塊。"""
    return largest_piece(~background_mask(rgb, tol))


# ------------------------------------------------------------ 輪廓


def _row_extents(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows = np.nonzero(mask.any(axis=1))[0]
    left = mask[rows].argmax(axis=1)
    right = mask.shape[1] - 1 - mask[rows][:, ::-1].argmax(axis=1)
    return rows, left, right


def _cord_rows(rows: np.ndarray, widths: np.ndarray) -> int:
    """頂端有幾列是電線：碰到照片頂端、很細、跟最上面一樣細的那一段夠長。

    沒碰到頂端就沒有電線。被照片切到的尖頂也很細，但一路變寬，
    跟頂端一樣細的只有短短幾列（Codex 審查）。
    電線接到燈座的地方寬度會變，所以只剪「跟最上面一樣細」的那段，燈座留著。
    """
    if rows[0] != 0 or widths[0] >= CORD_FRAC * widths.max():
        return 0
    wider = widths > widths[0] + CORD_WOBBLE
    run = int(np.argmax(wider)) if wider.any() else 0
    return run if run >= CORD_MIN_SHARE * len(widths) else 0


def _half_widths(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """每一列的半寬：中心軸到比較近的那一邊。影子只會讓一邊變寬。

    中心軸是上半部各列中點的中位數：影子落在底部，拖得很長也不會把中心軸拉走。
    """
    upper = max(1, int(len(left) * UPPER_SHARE))
    axis = float(np.median((left[:upper] + right[:upper]) / 2))
    return np.clip(np.minimum(axis - left, right - axis), 0, None)


def profile(mask: np.ndarray) -> PixelProfile:
    """前景 → [(從最低點算的高 px, 半寬 px), ...]，由下往上。"""
    rows, left, right = _row_extents(mask)
    if len(rows) == 0:
        raise NoProductError("照片裡找不到商品（整張都是背景）")
    cut = _cord_rows(rows, right - left)
    rows, halves = rows[cut:], _half_widths(left[cut:], right[cut:])
    bottom = rows.max()
    return sorted((int(bottom - r), float(w)) for r, w in zip(rows, halves, strict=True))


def _size_px(prof: PixelProfile) -> tuple[float, float]:
    """(最寬的半寬 px, 高 px)。有一個是 0 就是沒描到東西。"""
    widest, tallest = max(r for _, r in prof), max(h for h, _ in prof)
    if widest <= 0 or tallest <= 0:
        raise NoProductError("描出來的寬度或高度是 0")
    return widest, tallest


def to_cm(prof: PixelProfile, width_cm: float, height_cm: Cm = None) -> tuple[Profile, float]:
    """換成公分。回 ([(半徑 cm, 高 cm), ...], 用寬度量出來的高度 cm)。

    量出來的高度用來檢查照片角度（從下面拍的會偏高）。做 3D 時如果店家也標了高度，
    高度方向就照標的縮放（Codex 審查的建議）；沒標就跟著寬度的比例。
    """
    widest, tallest = _size_px(prof)
    scale = width_cm / (2 * widest)
    y_scale = height_cm / tallest if height_cm else scale
    return [(r * scale, h * y_scale) for h, r in prof], tallest * scale


def _distance(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return float(np.hypot(px - ax, py - ay))
    return abs(dy * px - dx * py + bx * ay - by * ax) / float(np.hypot(dx, dy))


def simplify(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker：離直線超過 tol 的點才留。頭尾一定留。"""
    if len(pts) < 3:
        return list(pts)
    far = max(range(1, len(pts) - 1), key=lambda i: _distance(pts[i], pts[0], pts[-1]))
    if _distance(pts[far], pts[0], pts[-1]) <= tol:
        return [pts[0], pts[-1]]
    return simplify(pts[: far + 1], tol)[:-1] + simplify(pts[far:], tol)


# ------------------------------------------------------------ 跟手描的比


def _radius_at(pts: list[tuple[float, float]], heights: np.ndarray) -> np.ndarray:
    """輪廓 [(半徑, 高)] 在各高度的半徑；範圍外是 0。"""
    ordered = sorted(pts, key=lambda p: p[1])
    hs = np.array([h for _, h in ordered])
    rs = np.array([r for r, _ in ordered])
    inside = (heights >= hs.min()) & (heights <= hs.max())
    return np.where(inside, np.interp(heights, hs, rs), 0.0)


def overlap(a: Profile, b: Profile, samples: int = 400) -> float:
    """兩個側面輪廓重疊的比例（交集 / 聯集），1 = 一模一樣。"""
    top = max(max(h for _, h in a), max(h for _, h in b))
    heights = np.linspace(0, top, samples)
    ra, rb = _radius_at(a, heights), _radius_at(b, heights)
    union = np.maximum(ra, rb).sum()
    return float(np.minimum(ra, rb).sum() / union) if union else 1.0


def _on_axis(part: dict) -> bool:
    at = part.get("at") or [0, 0, 0]
    return at[0] == 0 and at[2] == 0 and part.get("axis", "y") == "y"


def _lathe_r(part: dict, h: float) -> float:
    pts = [(r, y) for (r, _), y in zip(part["pts"], _lathe_heights(part), strict=True)]
    best = 0.0
    for (r1, y1), (r2, y2) in pairwise(pts):
        if min(y1, y2) <= h <= max(y1, y2):
            best = max(best, max(r1, r2) if y1 == y2 else r1 + (r2 - r1) * (h - y1) / (y2 - y1))
    return best


def _cyl_r(part: dict, h: float) -> float:
    y, length = part["at"][1], part["h"]
    bottom = y - length / 2
    if not bottom <= h <= bottom + length:
        return 0.0
    r_top, r_bottom = part["r"], part.get("r2", part["r"])
    return r_bottom + (r_top - r_bottom) * (h - bottom) / length


def _sphere_r(part: dict, h: float) -> float:
    half = part["r"] * part.get("sy", 1)
    t = (h - part["at"][1]) / half
    return part["r"] * float(np.sqrt(1 - t * t)) if abs(t) <= 1 else 0.0


_SHAPES = {"lathe": _lathe_r, "cyl": _cyl_r, "sphere": _sphere_r}


def _span(part: dict) -> tuple[float, float]:
    if part["k"] == "lathe":
        y0 = (part.get("at") or [0, 0, 0])[1]
        ys = [y + y0 for _, y in part["pts"]]
        return min(ys), max(ys)
    half = part["h"] / 2 if part["k"] == "cyl" else part["r"] * part.get("sy", 1)
    return part["at"][1] - half, part["at"][1] + half


def _axis_parts(parts: list[dict]) -> list[dict]:
    """在中心軸上的旋轉體、圓柱、球。電線、提把、方塊、偏到旁邊的支架不算。"""
    return [p for p in parts if p["k"] in _SHAPES and _on_axis(p)]


def parts_profile(parts: list[dict], step: float = 0.5) -> Profile:
    """原型手描的零件 → 側面輪廓 [(半徑, 高)]，最低點是 0。"""
    used = _axis_parts(parts)
    if not used:
        return []  # 壁燈這種：沒有「轉一圈」的形狀
    low, high = _extent(used)
    heights = np.union1d(np.arange(low, high + step / 2, step), _feature_heights(used))
    return [(max(_SHAPES[p["k"]](p, h) for p in used), float(h - low)) for h in heights]


def _feature_heights(parts: list[dict]) -> list[float]:
    """每個零件的上下緣、旋轉體的每個點：薄薄一片的凸緣才不會剛好落在兩個取樣點中間。"""
    edges = [y for p in parts for y in _span(p)]
    return edges + [y for p in parts if p["k"] == "lathe" for y in _lathe_heights(p)]


def _lathe_heights(part: dict) -> list[float]:
    y0 = (part.get("at") or [0, 0, 0])[1]
    return [y + y0 for _, y in part["pts"]]


def _extent(parts: list[dict]) -> tuple[float, float]:
    spans = [_span(p) for p in parts]
    return min(s[0] for s in spans), max(s[1] for s in spans)
