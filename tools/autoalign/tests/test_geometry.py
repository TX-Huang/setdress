"""用假房間（見 synthetic_room.py）測 fit_camera。"""

from __future__ import annotations

import numpy as np
import pytest
from synthetic_room import (
    BED,
    FUTON,
    LOW_PLATFORM,
    SIDE_TABLE,
    SOFA,
    SOFFIT,
    UPPER_CABINET,
    Shot,
    render,
    with_holes,
    with_noise,
    with_smooth_noise,
)

from geometry import CameraFit, NoFloorError, fit_camera


def fit(points: np.ndarray, fy: float) -> CameraFit:
    return fit_camera(points, fy, rng=np.random.default_rng(0))


def assert_matches(result: CameraFit, shot: Shot, *, cm: float = 1.0, deg: float = 0.5) -> None:
    assert result.height_m == pytest.approx(shot.height, abs=cm / 100)
    assert result.pitch_deg == pytest.approx(shot.pitch, abs=deg)
    assert result.roll_deg == pytest.approx(shot.roll, abs=deg)
    assert result.vfov_deg == pytest.approx(shot.vfov, abs=0.5)
    assert result.ceiling_m == pytest.approx(shot.ceiling, abs=2 * cm / 100)


def test_clean_room() -> None:
    shot = Shot()
    assert_matches(fit(*render(shot)), shot)


@pytest.mark.parametrize("roll", [-4.0, 5.0])
def test_tilted_and_rolled_camera(roll: float) -> None:
    shot = Shot(height=1.6, pitch=15.0, roll=roll, vfov=65.0, ceiling=2.9)
    assert_matches(fit(*render(shot)), shot)


def test_noisy_depth_stays_within_five_percent() -> None:
    shot = Shot()
    points, fy = render(shot)
    result = fit(with_noise(points, 0.02, seed=1), fy)
    assert result.height_m == pytest.approx(shot.height, rel=0.05)
    assert result.ceiling_m == pytest.approx(shot.ceiling, rel=0.05)
    assert result.pitch_deg == pytest.approx(shot.pitch, abs=2.0)
    assert result.roll_deg == pytest.approx(shot.roll, abs=2.0)


def test_missing_points_are_ignored() -> None:
    shot = Shot()
    points, fy = render(shot)
    assert_matches(fit(with_holes(points, 0.3, seed=2), fy), shot)


def test_sofa_and_table_are_not_the_floor() -> None:
    shot = Shot(boxes=(SOFA, SIDE_TABLE))
    assert_matches(fit(*render(shot)), shot)


def test_big_low_platform_is_not_the_floor() -> None:
    shot = Shot(boxes=(LOW_PLATFORM,))
    assert_matches(fit(*render(shot)), shot)


BEDROOM = Shot(height=1.6, pitch=20.0, vfov=65.0, width=120, rows=160, boxes=(BED,))
FLOOR_BED = Shot(height=0.87, pitch=-5.0, vfov=67.0, width=120, rows=160, boxes=(FUTON,))


@pytest.mark.parametrize("shot", [BEDROOM, FLOOR_BED], ids=["bed", "futon"])
def test_bed_covering_most_of_the_floor_is_not_the_floor(shot: Shot) -> None:
    result = fit(*render(shot))
    assert result.height_m == pytest.approx(shot.height, abs=0.01)
    assert result.pitch_deg == pytest.approx(shot.pitch, abs=0.5)
    assert result.roll_deg == pytest.approx(shot.roll, abs=0.5)


@pytest.mark.parametrize("seed", [3, 4, 5])
@pytest.mark.parametrize("shot", [BEDROOM, FLOOR_BED], ids=["bed", "futon"])
def test_bed_is_not_the_floor_when_depth_is_smoothly_wrong(shot: Shot, seed: int) -> None:
    points, fy = render(shot)
    result = fit(with_smooth_noise(points, 0.03, seed=seed), fy)
    assert result.height_m == pytest.approx(shot.height, rel=0.05)


def test_ceiling_out_of_view_is_unknown() -> None:
    shot = Shot(pitch=35.0, vfov=45.0)
    result = fit(*render(shot))
    assert result.ceiling_m is None
    assert result.height_m == pytest.approx(shot.height, abs=0.01)


def test_walls_above_camera_are_not_mistaken_for_ceiling() -> None:
    shot = Shot(pitch=5.0, vfov=26.0)
    result = fit(*render(shot))
    assert result.ceiling_m is None
    assert result.height_m == pytest.approx(shot.height, abs=0.01)


def test_floor_out_of_view_raises() -> None:
    shot = Shot(pitch=-12.0, vfov=30.0)
    with pytest.raises(NoFloorError):
        fit(*render(shot))


def test_rejects_wrong_shape() -> None:
    with pytest.raises(ValueError, match="列, 欄, 3"):
        fit_camera(np.zeros((10, 10)), 100.0)


def test_rejects_non_positive_focal_length() -> None:
    points, _ = render(Shot())
    with pytest.raises(ValueError, match="fy"):
        fit_camera(points, 0.0)


@pytest.mark.parametrize("seed", [3, 4, 5])
def test_ceiling_is_found_when_depth_is_smoothly_wrong(seed: int) -> None:
    # 示範房間用真的模型跑時就是這樣：天花板有拍到，但深度一大片一大片地偏，
    # 天花板那層變胖，原本「比牆密 4 倍」的規則就把它丟掉了。
    shot = Shot()
    points, fy = render(shot)
    result = fit(with_smooth_noise(points, 0.03, seed=seed), fy)
    assert result.height_m == pytest.approx(shot.height, rel=0.05)
    assert result.ceiling_m == pytest.approx(shot.ceiling, rel=0.05)


def test_wide_view_with_walls_above_camera_but_no_ceiling() -> None:
    shot = Shot(pitch=30.0, vfov=75.0)
    result = fit(*render(shot))
    assert result.ceiling_m is None
    assert result.height_m == pytest.approx(shot.height, abs=0.01)


def test_two_level_ceiling_gives_the_higher_one() -> None:
    shot = Shot(pitch=-5.0, vfov=65.0, ceiling=3.0, boxes=(SOFFIT,))
    result = fit(*render(shot))
    assert result.ceiling_m == pytest.approx(3.0, abs=0.02)
    assert result.height_m == pytest.approx(shot.height, abs=0.01)


def test_cabinet_bottom_just_above_the_camera_is_not_the_ceiling() -> None:
    shot = Shot(pitch=5.0, vfov=26.0, boxes=(UPPER_CABINET,))
    result = fit(*render(shot))
    assert result.ceiling_m is None


def test_layers_ignore_extreme_wrong_depths() -> None:
    from geometry import _layers

    values = np.array([1.35] * 500 + [2.7] * 200 + [9000.0, -8000.0])
    got = _layers(values)
    assert len(got) == 2
    assert got == pytest.approx([1.35, 2.7], abs=0.02)
