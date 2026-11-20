"""把 fit_camera 算出來的鏡頭放回照片，畫出 1 公尺的地板（和天花板）格線，給人眼檢查。

鏡頭的擺法跟原型（Three.js）一樣：在 (0, 鏡頭離地, 0)，往 -z 看，
先繞 x 軸轉 -pitch，再繞 z 軸轉 roll。像素是正方形，(0, 0) 是左上角。
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from geometry import CameraFit

GRID_STEP_M = 1.0
GRID_X_M = (-6.0, 6.0)
GRID_Z_M = (-12.0, 0.0)  # 鏡頭前方 12 公尺
SAMPLE_STEP_M = 0.05  # 把每條線切成小段，透視下才會畫對
FLOOR_COLOR = (111, 220, 255)
CEILING_COLOR = (190, 238, 255)
OCCLUDE_REL = 0.03  # 深度本來就有誤差，遠 3% + 5 cm 以內不算被擋
OCCLUDE_ABS_M = 0.05


def _rot_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def _rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def project(
    world: np.ndarray, fit: CameraFit, width: int, rows: int
) -> tuple[np.ndarray, np.ndarray]:
    """房間座標的點 (N, 3) → 像素座標 (N, 2) 和「在鏡頭前面」的遮罩 (N,)。"""
    world_from_cam = _rot_x(math.radians(-fit.pitch_deg)) @ _rot_z(math.radians(fit.roll_deg))
    cam = (world - np.array([0.0, fit.height_m, 0.0])) @ world_from_cam
    depth = -cam[:, 2]
    visible = depth > 1e-3
    f = (rows / 2) / math.tan(math.radians(fit.vfov_deg) / 2)
    safe = np.where(visible, depth, 1.0)
    u = width / 2 + f * cam[:, 0] / safe
    v = rows / 2 - f * cam[:, 1] / safe
    return np.stack([u, v], axis=1), visible


def _grid_lines(y: float) -> list[np.ndarray]:
    """高度 y 的水平面上，每隔 1 公尺一條線；每條線是一串密集的點 (N, 3)。"""
    xs = np.arange(GRID_X_M[0], GRID_X_M[1] + 1e-9, GRID_STEP_M)
    zs = np.arange(GRID_Z_M[0], GRID_Z_M[1] + 1e-9, GRID_STEP_M)
    along_x = np.arange(GRID_X_M[0], GRID_X_M[1] + 1e-9, SAMPLE_STEP_M)
    along_z = np.arange(GRID_Z_M[0], GRID_Z_M[1] + 1e-9, SAMPLE_STEP_M)

    def line(x: np.ndarray, z: np.ndarray) -> np.ndarray:
        return np.stack(np.broadcast_arrays(x, y, z), axis=1).astype(float)

    return [line(along_x, z) for z in zs] + [line(x, along_z) for x in xs]


def _draw_polyline(
    draw: ImageDraw.ImageDraw,
    px: np.ndarray,
    visible: np.ndarray,
    limit: float,
    style: tuple[tuple[int, int, int], int],
) -> None:
    """只畫兩端都在鏡頭前面、也沒有飛到畫面很遠外面的小段。"""
    color, width = style
    ok = visible & (np.abs(px) < limit).all(axis=1)
    for i in np.nonzero(ok[:-1] & ok[1:])[0]:
        draw.line([tuple(px[i]), tuple(px[i + 1])], fill=color, width=width)


def _occluded(line: np.ndarray, px: np.ndarray, fit: CameraFit, scene: np.ndarray) -> np.ndarray:
    """格線上的點，比照片裡同一個像素的東西還遠，就是被牆或家具擋住了。

    跟 IKEA Kreativ 遮擋商品的道理一樣：拿深度比，誰近誰就在前面。
    """
    rows, cols = scene.shape
    inside = (px[:, 0] >= 0) & (px[:, 0] < cols) & (px[:, 1] >= 0) & (px[:, 1] < rows)
    u = np.clip(px[:, 0], 0, cols - 1).astype(int)
    v = np.clip(px[:, 1], 0, rows - 1).astype(int)
    grid_dist = np.linalg.norm(line - np.array([0.0, fit.height_m, 0.0]), axis=1)
    with np.errstate(invalid="ignore"):
        return inside & (grid_dist > scene[v, u] * (1 + OCCLUDE_REL) + OCCLUDE_ABS_M)


def draw_grid(image: Image.Image, fit: CameraFit, points: np.ndarray | None = None) -> Image.Image:
    """回傳畫好格線的新圖，不改原圖。

    有給 points（跟照片一樣大的鏡頭座標點）時，被牆或家具擋住的格線不畫，
    這樣格線只會出現在看得到的地板和天花板上。
    """
    out = image.convert("RGB")
    scene = None if points is None else np.linalg.norm(points, axis=-1)
    if scene is not None and scene.shape != (out.height, out.width):
        raise ValueError("points 的大小要跟照片一樣")
    draw = ImageDraw.Draw(out)
    style_width = max(1, round(min(out.size) / 400))
    limit = 4.0 * max(out.size)
    levels = [(0.0, FLOOR_COLOR)]
    if fit.ceiling_m is not None:
        levels.append((fit.ceiling_m, CEILING_COLOR))
    for y, color in levels:
        for line in _grid_lines(y):
            px, visible = project(line, fit, out.width, out.height)
            if scene is not None:
                visible = visible & ~_occluded(line, px, fit, scene)
            _draw_polyline(draw, px, visible, limit, (color, style_width))
    return out
