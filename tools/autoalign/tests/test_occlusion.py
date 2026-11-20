"""遮擋用的深度圖：家具和牆會擋住商品，地板和天花板不會。"""

from __future__ import annotations

import numpy as np
import pytest
from synthetic_room import SOFA, Shot, render, to_world, with_holes

from geometry import _tilt_deg, fit_camera, up_vector
from occlusion import occluder_depth_mm

SHOT = Shot(boxes=(SOFA,))


@pytest.fixture(scope="module")
def scene() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """回傳 (點, 每個點的房間座標, 深度圖 mm)。"""
    points, fy = render(SHOT)
    fit = fit_camera(points, fy, rng=np.random.default_rng(0))
    return points, to_world(points, SHOT), occluder_depth_mm(points, fit)


@pytest.mark.parametrize(("pitch", "roll"), [(0.0, 0.0), (12.0, 3.0), (-5.0, -4.0), (40.0, 8.0)])
def test_up_vector_undoes_tilt(pitch: float, roll: float) -> None:
    assert _tilt_deg(up_vector(pitch, roll)) == pytest.approx((pitch, roll), abs=1e-9)


def test_same_size_as_the_points_when_small(scene: tuple) -> None:
    points, _, depth = scene
    assert depth.shape == points.shape[:2]
    assert depth.dtype == np.uint16


def test_floor_does_not_block(scene: tuple) -> None:
    _, world, depth = scene
    floor = world[..., 1] < 0.01
    assert floor.sum() > 1000
    assert np.all(depth[floor] == 0)


def test_ceiling_does_not_block(scene: tuple) -> None:
    _, world, depth = scene
    ceiling = world[..., 1] > SHOT.ceiling - 0.01
    assert ceiling.sum() > 500
    assert np.all(depth[ceiling] == 0)


def test_furniture_blocks_at_its_distance(scene: tuple) -> None:
    points, world, depth = scene
    x, y, z = world[..., 0], world[..., 1], world[..., 2]
    sofa = (y > 0.1) & (y < SOFA.hi[1] + 0.001) & (z > SOFA.lo[2] - 0.001) & (np.abs(x) < 1.2)
    assert sofa.sum() > 100
    assert depth[sofa] / 1000 == pytest.approx(points[..., 2][sofa], abs=0.001)


def test_walls_block(scene: tuple) -> None:
    _, world, depth = scene
    back_wall = (world[..., 2] < -5.99) & (world[..., 1] > 1.0) & (world[..., 1] < 2.0)
    assert back_wall.sum() > 100
    assert np.all(depth[back_wall] > 0)


def test_points_without_depth_do_not_block() -> None:
    points, fy = render(SHOT)
    fit = fit_camera(points, fy, rng=np.random.default_rng(0))
    holes = with_holes(points, 0.3, seed=2)
    depth = occluder_depth_mm(holes, fit)
    assert np.all(depth[np.isnan(holes).any(axis=-1)] == 0)


def test_big_depth_maps_are_shrunk() -> None:
    points, fy = render(Shot(width=1600, rows=1200, boxes=(SOFA,)))
    fit = fit_camera(points, fy, rng=np.random.default_rng(0))
    depth = occluder_depth_mm(points, fit, max_edge=512)
    assert depth.shape == (384, 512)


@pytest.mark.parametrize(("rows", "want"), [(769, 384), (771, 386)])
def test_shrinking_never_reads_outside_the_photo(rows: int, want: int) -> None:
    # 1024 寬縮到 512：771 乘 0.5 = 385.5 → 386（取偶數），最後一列的來源不能超過照片
    points, fy = render(Shot(width=1024, rows=rows, boxes=(SOFA,)))
    fit = fit_camera(points, fy, rng=np.random.default_rng(0))
    depth = occluder_depth_mm(points, fit, max_edge=512)
    full = occluder_depth_mm(points, fit, max_edge=4096)
    assert depth.shape == (want, 512)
    src = min(rows - 1, int((want - 0.5) / 0.5))
    assert depth[-1, 100] == full[src, 201]
