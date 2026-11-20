"""遮擋用的深度圖：每個像素離鏡頭多遠（往正前方量，mm）。

原型把它寫進 3D 的深度緩衝區，商品被家具或牆擋住的部分就不畫。
地板和天花板不擋東西（值是 0）：不然貼地的地毯、貼天花板的吊燈會被深度誤差亂切。
沒有深度的點也是 0。
"""

from __future__ import annotations

import numpy as np

from geometry import CameraFit, up_vector

# 離地板（或天花板）這麼近的點算是地板（或天花板）。越遠的點深度誤差越大，帶子跟著變寬：
# 3 cm + 每 1 公尺多 1 cm。太寬的話，家具最下面那段（沙發底座、桌腳）就擋不住地毯。
# 原型那邊還有「遠 3% + 5 cm 以內不算被擋」，貼地的東西不會被沒排除乾淨的地板點切掉。
SURFACE_BAND_M = 0.03
SURFACE_BAND_REL = 0.01
MAX_MM = np.iinfo(np.uint16).max


def occluder_depth_mm(points: np.ndarray, fit: CameraFit, max_edge: int = 512) -> np.ndarray:
    """points：(列, 欄, 3) 的鏡頭座標點。回傳 uint16 的 (列, 欄)，最長邊縮到 max_edge 以內。"""
    points = _shrink(points, max_edge)
    z = points[..., 2]
    with np.errstate(invalid="ignore"):
        height = points @ up_vector(fit.pitch_deg, fit.roll_deg) + fit.height_m
        band = SURFACE_BAND_M + SURFACE_BAND_REL * z
        open_space = ~np.isfinite(height) | ~(z > 0) | (height < band)
        if fit.ceiling_m is not None:
            open_space |= height > fit.ceiling_m - band
    mm = np.clip(np.nan_to_num(z * 1000), 1, MAX_MM).round().astype(np.uint16)
    mm[open_space] = 0
    return mm


def _shrink(points: np.ndarray, max_edge: int) -> np.ndarray:
    """取最近的點縮小（不平均）：平均會把前面的椅子和後面的牆混成一個不存在的深度。"""
    rows, cols = points.shape[:2]
    scale = max_edge / max(rows, cols)
    if scale >= 1:
        return points
    # round 是四捨六入五成雙：剛好 .5 往上進時，最後一格的來源會超出照片，要夾住
    r = np.minimum(((np.arange(round(rows * scale)) + 0.5) / scale).astype(int), rows - 1)
    c = np.minimum(((np.arange(round(cols * scale)) + 0.5) / scale).astype(int), cols - 1)
    return points[np.ix_(r, c)]
