"""電腦做出來的假房間：答案已知，讓測試量得出誤差。

假房間：地板 y = 0、天花板 y = 天花板高度、左右牆 x = ±2.5、後牆 z = -6、鏡頭後面的牆 z = 1。
鏡頭在 (0, 鏡頭離地, 0)，用 Three.js 的慣例擺：往 -z 看、往下看是正的 pitch、繞前方軸轉是 roll。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

ROOM_X = 2.5
ROOM_Z_BACK = -6.0
ROOM_Z_FRONT = 1.0


@dataclass(frozen=True)
class Box:
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]


SOFA = Box((-1.2, 0.0, -5.9), (1.2, 0.45, -5.0))
SIDE_TABLE = Box((-1.0, 0.72, -2.6), (1.0, 0.75, -1.6))
# 很大、很低的平台，蓋住照片下半部大部分：最容易被誤認成地板
LOW_PLATFORM = Box((-2.0, 0.42, -3.2), (2.0, 0.45, -1.5))
# 床和地上的床墊蓋住大部分地板，只露出一小條：實拍的臥室照片常常這樣。
# 真照片裡平躺的真地板只佔照片下半部 4.4 到 4.5% 的點；這裡的床照這個比例調（BED 約 4.0%）
BED = Box((-2.5, 0.0, -3.5), (0.7, 0.5, -0.2))
FUTON = Box((-2.5, 0.0, -4.0), (1.5, 0.22, -0.2))
# 天花板降一階（常見的格局）：後段從 3.0 m 降到 2.5 m
SOFFIT = Box((-2.5, 2.5, -6.0), (2.5, 3.0, -3.0))
# 廚房吊櫃：底面朝下、只比鏡頭高 15 cm，不是天花板
UPPER_CABINET = Box((-2.5, 1.5, -6.0), (2.5, 2.3, -3.5))


@dataclass(frozen=True)
class Shot:
    height: float = 1.35
    pitch: float = 10.0
    roll: float = 0.0
    vfov: float = 55.0
    ceiling: float = 2.7
    width: int = 160
    rows: int = 120
    boxes: tuple[Box, ...] = ()


def _rot_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def _rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _hit_room(origin: np.ndarray, dirs: np.ndarray, ceiling: float) -> np.ndarray:
    t = np.full(dirs.shape[:2], np.inf)
    planes = [
        (1, 0.0),
        (1, ceiling),
        (0, -ROOM_X),
        (0, ROOM_X),
        (2, ROOM_Z_BACK),
        (2, ROOM_Z_FRONT),
    ]
    for axis, value in planes:
        with np.errstate(divide="ignore", invalid="ignore"):
            tt = (value - origin[axis]) / dirs[..., axis]
        t = np.minimum(t, np.where(tt > 1e-6, tt, np.inf))
    return t


def _hit_box(origin: np.ndarray, dirs: np.ndarray, box: Box) -> np.ndarray:
    lo, hi = np.array(box.lo), np.array(box.hi)
    with np.errstate(divide="ignore", invalid="ignore"):
        t1 = (lo - origin) / dirs
        t2 = (hi - origin) / dirs
    t_near = np.max(np.minimum(t1, t2), axis=-1)
    t_far = np.min(np.maximum(t1, t2), axis=-1)
    hit = (t_far >= t_near) & (t_near > 1e-6)
    return np.where(hit, t_near, np.inf)


def render(shot: Shot) -> tuple[np.ndarray, float]:
    """回傳 OpenCV 鏡頭座標（x 右、y 下、z 前）的點陣列 (列, 欄, 3) 和 fy。"""
    fy = (shot.rows / 2) / math.tan(math.radians(shot.vfov) / 2)
    j, i = np.mgrid[0 : shot.rows, 0 : shot.width].astype(float)
    dirs_cam = np.stack(
        [(i + 0.5 - shot.width / 2) / fy, -(j + 0.5 - shot.rows / 2) / fy, -np.ones_like(i)],
        axis=-1,
    )
    world_from_cam = _rot_x(math.radians(-shot.pitch)) @ _rot_z(math.radians(shot.roll))
    dirs = dirs_cam @ world_from_cam.T
    origin = np.array([0.0, shot.height, 0.0])
    t = _hit_room(origin, dirs, shot.ceiling)
    for box in shot.boxes:
        t = np.minimum(t, _hit_box(origin, dirs, box))
    world = origin + dirs * t[..., None]
    cam = (world - origin) @ world_from_cam
    return cam * np.array([1.0, -1.0, -1.0]), fy


def with_noise(points: np.ndarray, rel: float, seed: int) -> np.ndarray:
    """沿著視線方向加雜訊：每個點的距離乘上 (1 + rel * 常態分布)。"""
    rng = np.random.default_rng(seed)
    return points * (1 + rel * rng.standard_normal(points.shape[:2]))[..., None]


def with_smooth_noise(points: np.ndarray, rel: float, seed: int, cells: int = 6) -> np.ndarray:
    """像真的深度模型那樣錯：距離錯得「一大片一大片」、慢慢變化，不是每個點各錯各的。

    做法：在每邊 cells 格的粗格子上抽亂數，再平滑放大到整張圖，乘到每個點的距離上。
    """
    rng = np.random.default_rng(seed)
    coarse = rng.standard_normal((cells, cells))
    rows, cols = points.shape[:2]
    ys, xs = np.linspace(0, cells - 1, rows), np.linspace(0, cells - 1, cols)
    y0 = np.minimum(ys.astype(int), cells - 2)
    x0 = np.minimum(xs.astype(int), cells - 2)
    wy, wx = (ys - y0)[:, None], (xs - x0)[None, :]
    field = (
        coarse[np.ix_(y0, x0)] * (1 - wy) * (1 - wx)
        + coarse[np.ix_(y0 + 1, x0)] * wy * (1 - wx)
        + coarse[np.ix_(y0, x0 + 1)] * (1 - wy) * wx
        + coarse[np.ix_(y0 + 1, x0 + 1)] * wy * wx
    )
    return points * (1 + rel * field)[..., None]


def with_holes(points: np.ndarray, share: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = points.copy()
    out[rng.random(points.shape[:2]) < share] = np.nan
    return out


def world_from_cam(shot: Shot) -> np.ndarray:
    return _rot_x(math.radians(-shot.pitch)) @ _rot_z(math.radians(shot.roll))


def to_world(points_cv: np.ndarray, shot: Shot) -> np.ndarray:
    """把 OpenCV 鏡頭座標的點換回房間座標。"""
    cam = points_cv * np.array([1.0, -1.0, -1.0])
    return np.array([0.0, shot.height, 0.0]) + cam @ world_from_cam(shot).T
