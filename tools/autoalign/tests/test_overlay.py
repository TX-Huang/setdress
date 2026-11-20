"""把算出來的鏡頭放回照片：地板上的點要落回照片裡同一個像素，格線要畫在對的地方。"""

from __future__ import annotations

import math

import numpy as np
import pytest
from PIL import Image
from synthetic_room import Shot, render, to_world

from geometry import CameraFit
from overlay import draw_grid, project


def fit_of(shot: Shot, *, ceiling: bool = True) -> CameraFit:
    return CameraFit(
        height_m=shot.height,
        pitch_deg=shot.pitch,
        roll_deg=shot.roll,
        vfov_deg=shot.vfov,
        ceiling_m=shot.ceiling if ceiling else None,
        floor_inlier_ratio=1.0,
    )


@pytest.mark.parametrize(
    "shot",
    [Shot(), Shot(height=1.6, pitch=15.0, roll=-4.0, vfov=65.0, ceiling=2.9)],
)
def test_floor_points_land_on_their_own_pixels(shot: Shot) -> None:
    points, _ = render(shot)
    world = to_world(points, shot)
    rows, cols = np.nonzero(np.abs(world[..., 1]) < 1e-6)
    pick = np.linspace(0, len(rows) - 1, 50).astype(int)
    px, visible = project(world[rows[pick], cols[pick]], fit_of(shot), shot.width, shot.rows)
    assert visible.all()
    np.testing.assert_allclose(px[:, 0], cols[pick] + 0.5, atol=1e-6)
    np.testing.assert_allclose(px[:, 1], rows[pick] + 0.5, atol=1e-6)


def test_points_behind_the_camera_are_not_visible() -> None:
    shot = Shot()
    _, visible = project(np.array([[0.0, 0.0, 2.0]]), fit_of(shot), shot.width, shot.rows)
    assert not visible[0]


def _changed_rows(shot: Shot, fit: CameraFit) -> np.ndarray:
    blank = Image.new("RGB", (shot.width, shot.rows), (90, 90, 90))
    drawn = np.asarray(draw_grid(blank, fit))
    return np.nonzero((drawn != 90).any(axis=(1, 2)))[0]


def _horizon_row(shot: Shot) -> float:
    fy = (shot.rows / 2) / math.tan(math.radians(shot.vfov) / 2)
    return shot.rows / 2 - fy * math.tan(math.radians(shot.pitch))


def test_floor_grid_stays_below_the_horizon() -> None:
    shot = Shot()
    rows = _changed_rows(shot, fit_of(shot, ceiling=False))
    assert len(rows) > 0
    assert rows.min() > _horizon_row(shot)


def test_ceiling_grid_is_drawn_above_the_horizon_when_known() -> None:
    shot = Shot()
    rows = _changed_rows(shot, fit_of(shot, ceiling=True))
    assert rows.min() < _horizon_row(shot) - 5


def test_draw_grid_keeps_the_original_image() -> None:
    shot = Shot()
    blank = Image.new("RGB", (shot.width, shot.rows), (90, 90, 90))
    draw_grid(blank, fit_of(shot))
    assert np.asarray(blank).max() == 90


def test_grid_is_hidden_where_walls_and_furniture_are_in_front() -> None:
    from synthetic_room import SOFA

    shot = Shot(boxes=(SOFA,))
    points, _ = render(shot)
    world = to_world(points, shot)
    blank = Image.new("RGB", (shot.width, shot.rows), (90, 90, 90))
    drawn = np.asarray(draw_grid(blank, fit_of(shot), points=points))
    changed = (drawn != 90).any(axis=-1)
    # 離地板和天花板都超過 15 cm 的，一定是牆或沙發。交界處線條粗細會沾到一點，不算。
    height = world[..., 1]
    clearly_wall_or_sofa = (height > 0.15) & (height < shot.ceiling - 0.15)
    assert changed.sum() > 100
    # 沒有遮擋時約 66% 的線畫在牆和沙發上；有遮擋要壓到 2% 以下
    assert (changed & clearly_wall_or_sofa).sum() <= 0.02 * changed.sum()
