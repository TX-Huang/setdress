"""從深度模型的 3D 點算出鏡頭離地、角度、視角和天花板高度。

輸入的點用 OpenCV 鏡頭座標：x 往右、y 往下、z 往前，單位公尺。
輸出的角度用原型（Three.js）的慣例：往下看是正的 pitch，歪斜是繞鏡頭前方軸的 roll。

步驟：
1. 照片下半部的點用 RANSAC 找出最大的「接近水平」的平面，得到「往上」的方向。
2. 只看平躺的表面，沿著「往上」看每個點在鏡頭下方多深，分層；
   最低、點又夠多（至少佔下半部 3%）的那層是地板。
   這樣大桌面、矮平台、沙發座墊、蓋住大半地板的床都不會被當成地板。
3. 用地板那層的點重新擬合平面，得到鏡頭離地和精確的「往上」方向。
4. 照片上半部、比鏡頭高、表面朝下的那層是天花板；找不到就回傳 None。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

UP_CV = np.array([0.0, -1.0, 0.0])  # 手機大致拿正時，「往上」在 OpenCV 座標是 -y
MAX_TILT_DEG = 50.0  # 「往上」最多偏離 -y 這麼多度
FLOOR_REGION = 0.4  # 照片最下面 40% 的列拿來找地板
CEILING_REGION = 0.4  # 照片最上面 40% 的列拿來找天花板
RANSAC_ITERS = 300
MAX_SAMPLES = 20_000
MIN_POINTS = 200
MIN_PLANE_SHARE = 0.1  # 最大的水平面至少佔下半部有效點的 10%，不然就是沒拍到地板
# 地板至少佔下半部有效點的 3%。床蓋住大半地板時，真的地板常常只露出 4 到 5%
FLOOR_MIN_SHARE = 0.03
MIN_CAMERA_HEIGHT_M = 0.3
BIN_M = 0.02  # 分層用的格子大小
LAYER_KERNEL = np.array([1.0, 2.0, 3.0, 4.0, 3.0, 2.0, 1.0])  # 約 14 cm 的平滑
LAYER_MIN_SUPPORT = 0.25  # 一層至少要有最密那層 25% 的密度
LAYER_MIN_GAP_M = 0.15  # 距離小於這個的兩層當成同一層
LAYER_HALF_WIDTH_M = 0.08
REFINE_ITERS = 3
MIN_REFINE_TOL_M = 0.01
CEILING_MIN_ABOVE_CAMERA_M = 0.3
CEILING_MIN_SHARE = 0.03  # 天花板至少佔上半部有效點的 3%
FLAT_MAX_TILT_DEG = 25.0  # 表面朝向跟「往上」差不到這麼多度，才算平躺（地板、天花板）
NORMAL_STEP_PX = 2  # 算表面朝向時，往左右、上下各隔幾個像素取點


class NoFloorError(ValueError):
    """照片裡找不到地板。"""


@dataclass(frozen=True)
class CameraFit:
    height_m: float
    pitch_deg: float
    roll_deg: float
    vfov_deg: float
    ceiling_m: float | None
    floor_inlier_ratio: float


def fit_camera(
    points: np.ndarray, fy: float, *, rng: np.random.Generator | None = None
) -> CameraFit:
    """points：(列, 欄, 3) 的鏡頭座標點；沒有深度的點用 NaN。fy：垂直方向的焦距（像素）。"""
    _check_input(points, fy)
    rng = rng if rng is not None else np.random.default_rng(0)
    valid = np.isfinite(points).all(axis=-1) & (points[..., 2] > 0)

    normals = _grid_normals(points)
    bottom = _rows(points, valid, 1.0 - FLOOR_REGION, 1.0)
    rough = _dominant_plane(bottom, rng)
    bottom_flat = _is_flat(_rows(normals, valid, 1.0 - FLOOR_REGION, 1.0), rough[0])
    up, height, floor_count = _fit_floor(bottom, bottom_flat, rough)
    pitch, roll = _tilt_deg(up)

    top = _rows(points, valid, 0.0, CEILING_REGION)
    top_normals = _rows(normals, valid, 0.0, CEILING_REGION)
    return CameraFit(
        height_m=height,
        pitch_deg=pitch,
        roll_deg=roll,
        vfov_deg=math.degrees(2 * math.atan(points.shape[0] / 2 / fy)),
        ceiling_m=_ceiling_height(top, top_normals, up, height),
        floor_inlier_ratio=floor_count / len(bottom),
    )


def _check_input(points: np.ndarray, fy: float) -> None:
    if points.ndim != 3 or points.shape[-1] != 3:
        raise ValueError("points 要是 (列, 欄, 3) 的陣列")
    if not fy > 0:
        raise ValueError("fy 要大於 0")


def _rows(points: np.ndarray, valid: np.ndarray, start: float, stop: float) -> np.ndarray:
    n = points.shape[0]
    lo, hi = round(n * start), round(n * stop)
    return points[lo:hi][valid[lo:hi]]


def _grid_normals(points: np.ndarray) -> np.ndarray:
    """每個像素的表面朝向（單位向量），用左右、上下相隔幾個像素的點算；算不出來是 NaN。"""
    s = NORMAL_STEP_PX
    dx = np.full_like(points, np.nan)
    dy = np.full_like(points, np.nan)
    if min(points.shape[:2]) > 2 * s:
        dx[:, s:-s] = points[:, 2 * s :] - points[:, : -2 * s]
        dy[s:-s, :] = points[2 * s :, :] - points[: -2 * s, :]
    n = np.cross(dx, dy)
    with np.errstate(invalid="ignore", divide="ignore"):
        return n / np.linalg.norm(n, axis=-1, keepdims=True)


def _is_flat(normals: np.ndarray, up: np.ndarray) -> np.ndarray:
    """表面是不是平躺的（朝上或朝下）。牆、櫃子正面、床的側面都是直立的。"""
    with np.errstate(invalid="ignore"):
        return np.abs(normals @ up) > math.cos(math.radians(FLAT_MAX_TILT_DEG))


def _tolerance(pts: np.ndarray) -> np.ndarray:
    """離鏡頭越遠，深度越不準，容許的誤差也放寬。"""
    return 0.02 + 0.01 * pts[:, 2]


def _upward_normal(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray | None:
    """三點決定的平面法向量，朝上；三點共線或平面太斜就回傳 None。"""
    n = np.cross(b - a, c - a)
    norm = np.linalg.norm(n)
    if norm < 1e-9:
        return None
    n = n / norm
    if n @ UP_CV < 0:
        n = -n
    return n if n @ UP_CV >= math.cos(math.radians(MAX_TILT_DEG)) else None


def _score(residual: np.ndarray, tol: np.ndarray) -> float:
    """MSAC 評分：點越貼近平面分數越高，超過容許誤差就是 0。

    只數「落在容許誤差內有幾個點」的話，地板只露出窄窄一條時，
    一個稍微斜的平面可以同時吃到地板和牆腳，反而贏過真的地板。
    """
    return float(np.sum(np.clip(1.0 - (residual / tol) ** 2, 0.0, None)))


def _dominant_plane(pts: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, float]:
    """最大的水平面：回傳朝上的 n 和它在鏡頭下方多深。通常是地板，但床很大時是床面。"""
    if len(pts) < MIN_POINTS:
        raise NoFloorError("看不到地板：照片下半部的點太少")
    sample = pts[rng.choice(len(pts), size=min(len(pts), MAX_SAMPLES), replace=False)]
    tol = _tolerance(sample)
    best_score, best = 0.0, None
    for _ in range(RANSAC_ITERS):
        a, b, c = sample[rng.choice(len(sample), size=3, replace=False)]
        n = _upward_normal(a, b, c)
        score = 0.0 if n is None else _score(np.abs((sample - a) @ n), tol)
        if score > best_score:
            best_score, best = score, (n, a)
    if best is None:
        raise NoFloorError("看不到地板：找不到夠大的水平面")
    n, a = best
    inliers = sample[np.abs((sample - a) @ n) < tol]
    if len(inliers) < MIN_PLANE_SHARE * len(sample):
        raise NoFloorError("看不到地板：找不到夠大的水平面")
    return n, float(np.median(-(inliers @ n)))


def _layers(values: np.ndarray, min_support: float = LAYER_MIN_SUPPORT) -> np.ndarray:
    """把高度分層，回傳每層的中心（由小到大）。

    一層的密度至少要有最密那層的 min_support 倍；給 0 就是每個高峰都算。
    """
    edges = np.arange(values.min() - 4 * BIN_M, values.max() + 5 * BIN_M, BIN_M)
    counts, _ = np.histogram(values, bins=edges)
    density = np.convolve(counts, LAYER_KERNEL, mode="same")
    peak = (
        (density >= np.roll(density, 1))
        & (density > np.roll(density, -1))
        & (density >= min_support * density.max())
    )
    centers = (edges[:-1] + edges[1:]) / 2
    return _merge_close(centers[peak], density[peak])


def _merge_close(centers: np.ndarray, weights: np.ndarray) -> np.ndarray:
    kept: list[tuple[float, float]] = []
    for c, w in zip(centers, weights, strict=True):
        if kept and c - kept[-1][0] < LAYER_MIN_GAP_M:
            if w > kept[-1][1]:
                kept[-1] = (c, w)
            continue
        kept.append((c, w))
    return np.array([c for c, _ in kept])


def _parallel_planes(groups: list[np.ndarray]) -> tuple[np.ndarray, list[float]]:
    """最小平方法擬合幾個互相平行的平面 n·p + d = 0（例如地板和床面），共用朝上的 n。

    第一群是地板，點太少就是看不到地板；其他群點太少就不用。只有一群時就是一般的平面擬合。
    回傳 n 和留下來的每群的 d。
    """
    if len(groups[0]) < MIN_POINTS:
        raise NoFloorError("看不到地板：地板的點太少")
    kept = [groups[0], *(g for g in groups[1:] if len(g) >= MIN_POINTS)]
    centroids = [g.mean(axis=0) for g in kept]
    centered = np.concatenate([g - c for g, c in zip(kept, centroids, strict=True)])
    n = np.linalg.svd(centered, full_matrices=False)[2][-1]
    if n @ UP_CV < 0:
        n = -n
    return n, [float(-n @ c) for c in centroids]


def _floor_level(below: np.ndarray, flat: np.ndarray) -> float:
    """平躺的點裡，最低、點又夠多的那層（鏡頭下方多深）。

    不跟最密的那層比，而是看佔下半部多少：床蓋住大半地板時，
    床面比露出來的那一小條地板密十幾倍，跟最密那層比就會把真的地板丟掉。
    """
    lying = below[flat & (below > 0)]
    if len(lying) < MIN_POINTS:
        raise NoFloorError("看不到地板：照片下半部沒有平躺的表面")
    need = FLOOR_MIN_SHARE * len(below)
    levels = [
        c
        for c in _layers(lying, min_support=0.0)
        if np.count_nonzero(np.abs(lying - c) < LAYER_HALF_WIDTH_M) >= need
    ]
    if not levels:
        raise NoFloorError("看不到地板：平躺的表面太少")
    return max(levels)


def _fit_floor(
    bottom: np.ndarray, flat: np.ndarray, rough: tuple[np.ndarray, float]
) -> tuple[np.ndarray, float, int]:
    rough_up, main_level = rough
    below = -(bottom @ rough_up)
    floor_level = _floor_level(below, flat)
    levels = [floor_level]
    if floor_level - main_level >= LAYER_MIN_GAP_M:
        # 最大的水平面不是地板（例如床面）。只露出一小條地板時，單用那一條算方向會歪；
        # 床面跟地板平行，一起算方向，高度還是只看地板
        levels.append(main_level)
    groups = [bottom[flat & (np.abs(below - lvl) < LAYER_HALF_WIDTH_M)] for lvl in levels]
    tol = _tolerance(bottom)
    for step in range(REFINE_ITERS):
        up, offsets = _parallel_planes(groups)
        # 容許誤差一輪比一輪緊，把牆腳那一小條點慢慢擠出去
        step_tol = np.maximum(tol * 0.5**step, MIN_REFINE_TOL_M)
        tighter = [bottom[np.abs(bottom @ up + d) < step_tol] for d in offsets]
        if len(tighter[0]) < MIN_POINTS:
            break  # 地板只有一小條、深度又一大片偏掉時，再擠就沒點了：用上一輪的
        groups = tighter
    up, offsets = _parallel_planes(groups)
    height = offsets[0]
    floor_count = int(np.count_nonzero(np.abs(bottom @ up + height) < tol))
    _check_floor(up, height, floor_count, len(bottom))
    return up, height, floor_count


def _check_floor(up: np.ndarray, height: float, count: int, total: int) -> None:
    if up @ UP_CV < math.cos(math.radians(MAX_TILT_DEG)):
        raise NoFloorError("看不到地板：找到的平面不是水平的")
    if height < MIN_CAMERA_HEIGHT_M:
        raise NoFloorError("看不到地板：找到的平面離鏡頭太近")
    if count < FLOOR_MIN_SHARE * total:
        raise NoFloorError("看不到地板：地板的點太少")


def _tilt_deg(up: np.ndarray) -> tuple[float, float]:
    """把 OpenCV 座標的「往上」換成 Three.js 的 pitch（往下看為正）和 roll。"""
    ux, uy, uz = up[0], -up[1], -up[2]
    pitch = math.degrees(math.asin(float(np.clip(uz, -1.0, 1.0))))
    roll = math.degrees(math.atan2(ux, uy))
    return pitch, roll


def up_vector(pitch_deg: float, roll_deg: float) -> np.ndarray:
    """_tilt_deg 的反過來：Three.js 的 pitch、roll → OpenCV 座標的「往上」單位向量。"""
    p, r = math.radians(pitch_deg), math.radians(roll_deg)
    return np.array([math.cos(p) * math.sin(r), -math.cos(p) * math.cos(r), -math.sin(p)])


def _ceiling_height(
    top: np.ndarray, normals: np.ndarray, up: np.ndarray, camera_height: float
) -> float | None:
    """比鏡頭高、表面朝下（跟地板平行）的點裡，最高、點又夠多的那層。

    用表面朝向分，而不是看「哪個高度的點特別擠」：牆在每個高度都有點，
    深度一大片一大片偏掉時，天花板那層會變胖，跟牆分不開；但牆是直立的，天花板是平躺的。
    """
    if len(top) == 0:
        return None
    heights = top @ up + camera_height
    flat = _is_flat(normals, up)
    above = heights[flat & (heights > camera_height + CEILING_MIN_ABOVE_CAMERA_M)]
    if len(above) < CEILING_MIN_SHARE * len(top):
        return None
    level = _layers(above)[-1]
    support = above[np.abs(above - level) < LAYER_HALF_WIDTH_M]
    if len(support) < CEILING_MIN_SHARE * len(top):
        return None
    return float(np.median(support))
