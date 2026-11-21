"""AI 生的形狀整理：轉正、放到地上、從正面投影照片的座標、準備給模型的照片。

說明在 docs/model3d.md。只用 numpy，不用 AI 模型（測試不用顯示卡）。

座標：x 往右、y 往上、z 朝鏡頭（照片那一面朝 +Z）。
照片座標：u 往右、v 往下（glTF 一樣，0 是最上面）。
"""

from __future__ import annotations

from itertools import permutations, product

import numpy as np

SIL_RES = 64  # 比輪廓用的解析度
MAX_SAMPLES = 2_000_000  # 畫輪廓時最多撒這麼多點
DENSITY = 8  # 每一格平均撒幾點（太少輪廓會有洞）
PAD = 0.1  # 給模型的照片：商品四周留長邊的一成（TripoSG 範例的做法）
# TripoSG 生的形狀本來就是照片那一面朝 +Z（沙發試過）：別的轉法要好這麼多才轉，
# 不然前後對稱的椅子差一點點就被轉成背面朝前（Codex 審查）
MARGIN = 0.05


def rotations() -> list[np.ndarray]:
    """24 種轉法（每個軸換成另一個軸、正或負，不鏡射）。

    不轉的排第一（一樣好時選它）：permutations、product 第一個就是 (0, 1, 2)、(1, 1, 1)。
    """
    out = []
    for perm in permutations(range(3)):
        for signs in product((1, -1), repeat=3):
            m = np.zeros((3, 3))
            m[range(3), perm] = signs
            if np.isclose(np.linalg.det(m), 1):
                out.append(m)
    return out


def _fit(x: np.ndarray, y: np.ndarray, res: int) -> np.ndarray:
    """點（x 往右、y 往下）照比例縮進 res x res、置中，回填好的格子。"""
    x0, y0 = x.min(), y.min()
    size = max(x.max() - x0, y.max() - y0) or 1.0
    scale = res / size * (1 - 1e-9)  # 最大的那個點落在最後一格裡，不跑到下一格
    ox = (res - (x.max() - x0) * scale) / 2
    oy = (res - (y.max() - y0) * scale) / 2
    col = np.clip(((x - x0) * scale + ox).astype(int), 0, res - 1)
    row = np.clip(((y - y0) * scale + oy).astype(int), 0, res - 1)
    grid = np.zeros((res, res), dtype=bool)
    grid[row, col] = True
    return grid


def _samples(tri: np.ndarray, res: int) -> np.ndarray:
    """三角形（n, 3, 2）上撒點：每個三角形照它在畫面上的大小撒（小的至少一點）。"""
    span = max(np.ptp(tri[..., 0]), np.ptp(tri[..., 1])) or 1.0
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    ab, ac = b - a, c - a
    area = 0.5 * np.abs(ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]) * (res / span) ** 2
    count = np.minimum(np.ceil(area * DENSITY).astype(int) + 1, MAX_SAMPLES // max(len(tri), 1) + 1)
    rng = np.random.default_rng(0)
    idx = np.repeat(np.arange(len(tri)), count)
    r1, r2 = rng.random(len(idx)), rng.random(len(idx))
    flip = r1 + r2 > 1
    r1[flip], r2[flip] = 1 - r1[flip], 1 - r2[flip]
    pts = a[idx] + (b[idx] - a[idx]) * r1[:, None] + (c[idx] - a[idx]) * r2[:, None]
    return np.vstack([pts, tri.reshape(-1, 2)])


def silhouette(v: np.ndarray, f: np.ndarray, res: int = SIL_RES) -> np.ndarray:
    """從 +Z 看過去的輪廓（res x res，照比例置中；第一列是最上面）。"""
    pts = _samples(v[f][..., :2].astype(float), res)
    return _fit(pts[:, 0], -pts[:, 1], res)


def photo_silhouette(alpha: np.ndarray, res: int = SIL_RES) -> np.ndarray:
    """去背照片的輪廓，跟 silhouette 同一種框法：每一格回去照片裡看那個位置是不是商品。"""
    rows, cols = np.nonzero(alpha >= 128)
    crop = alpha[rows.min() : rows.max() + 1, cols.min() : cols.max() + 1] >= 128
    h, w = crop.shape
    scale = res / max(w, h)
    rr, cc = np.mgrid[:res, :res] + 0.5
    sx = np.floor((cc - (res - w * scale) / 2) / scale).astype(int)
    sy = np.floor((rr - (res - h * scale) / 2) / scale).astype(int)
    inside = (sx >= 0) & (sx < w) & (sy >= 0) & (sy < h)
    grid = np.zeros((res, res), dtype=bool)
    grid[inside] = crop[sy[inside], sx[inside]]
    return grid


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    return float((a & b).sum() / max((a | b).sum(), 1))


def pick(scores: list[float]) -> int:
    """選哪一種轉法：不轉（第 0 個）優先，別的要好 MARGIN 以上才換。"""
    best = max(range(len(scores)), key=lambda i: scores[i])
    return best if scores[best] > scores[0] + MARGIN else 0


def orient(v: np.ndarray, f: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, float]:
    """轉成「照片那一面朝 +Z、上面朝 +Y」：24 種轉法裡，從 +Z 看的輪廓跟照片最像的那個。

    回 (轉好的點, 輪廓重疊比例 0 到 1)。
    """
    target = photo_silhouette(alpha)
    turns = rotations()
    scores = [_iou(silhouette(v @ m.T, f), target) for m in turns]
    k = pick(scores)
    return (v @ turns[k].T).astype(np.float32), scores[k]


def place(v: np.ndarray) -> np.ndarray:
    """底部放在 y = 0，左右、前後置中。"""
    lo, hi = v.min(axis=0), v.max(axis=0)
    shift = np.array([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2])
    return (v + shift).astype(np.float32)


def photo_uv(v: np.ndarray, box_px, photo_wh) -> np.ndarray:
    """每個點從正面（+Z）投影回照片：3D 的左右上下範圍對到照片裡商品的範圍。

    box_px：照片裡商品的範圍 [x0, y0, x1, y1]（px）；photo_wh：照片的寬、高（px）。
    回照片座標（0 到 1，v 往下）。背面、側面拿正面同一個位置。
    """
    x0, y0, x1, y1 = box_px
    w, h = photo_wh
    lo, hi = v.min(axis=0), v.max(axis=0)
    sx = (v[:, 0] - lo[0]) / ((hi[0] - lo[0]) or 1.0)
    sy = (hi[1] - v[:, 1]) / ((hi[1] - lo[1]) or 1.0)
    return np.stack([(x0 + sx * (x1 - x0)) / w, (y0 + sy * (y1 - y0)) / h], axis=1).astype(
        np.float32
    )


def model_input(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """給模型的照片：只留商品、白底、裁成正方形、四周留長邊的一成。"""
    rows, cols = np.nonzero(alpha >= 128)
    y0, y1, x0, x1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
    a = (alpha[y0:y1, x0:x1, None] >= 128).astype(float)
    crop = rgb[y0:y1, x0:x1, :3] * a + 255 * (1 - a)
    h, w = crop.shape[:2]
    side = max(w, h)
    pad = int(side * PAD)
    out = np.full((side + 2 * pad, side + 2 * pad, 3), 255, dtype=np.uint8)
    top, left = pad + (side - h) // 2, pad + (side - w) // 2
    out[top : top + h, left : left + w] = crop.round().astype(np.uint8)
    return out
