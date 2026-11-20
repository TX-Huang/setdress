"""測試工具裡不需要 AI 模型的部分：讀天花板實量值、算誤差、整理成表。"""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluate import PhotoResult, load_truth, render_markdown, summarize, truth_for
from geometry import CameraFit


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "ceilings.csv"
    p.write_text(text, encoding="utf-8")
    return p


def test_reads_one_height_per_photo(tmp_path: Path) -> None:
    truth = load_truth(_write(tmp_path, "photo,ceiling_m\nliving.jpg,2.75\nbed.jpg,2.6\n"))
    assert truth == {"living.jpg": 2.75, "bed.jpg": 2.6}


def test_star_row_applies_to_photos_without_their_own_height(tmp_path: Path) -> None:
    truth = load_truth(_write(tmp_path, "photo,ceiling_m\n*,2.8\nbed.jpg,2.6\n"))
    assert truth_for(truth, "kitchen.jpg") == 2.8
    assert truth_for(truth, "bed.jpg") == 2.6


def test_no_file_means_no_heights(tmp_path: Path) -> None:
    truth = load_truth(tmp_path / "missing.csv")
    assert truth == {}
    assert truth_for(truth, "living.jpg") is None


def test_bad_number_names_the_line(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="第 3 行"):
        load_truth(_write(tmp_path, "photo,ceiling_m\nliving.jpg,2.7\nbed.jpg,abc\n"))


def test_centimetres_are_rejected_with_a_hint(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="公尺"):
        load_truth(_write(tmp_path, "photo,ceiling_m\nliving.jpg,275\n"))


def _fit(ceiling: float | None) -> CameraFit:
    return CameraFit(1.4, 10.0, 0.0, 60.0, ceiling, 0.5)


def _results() -> list[PhotoResult]:
    return [
        PhotoResult("moge-2-s", "a.jpg", 2.0, _fit(2.7), None, 2.7),
        PhotoResult("moge-2-s", "b.jpg", 4.0, _fit(3.0), None, 2.5),
        PhotoResult("moge-2-s", "c.jpg", 3.0, None, "看不到地板", 2.6),
        PhotoResult("moge-2-s", "d.jpg", 3.0, _fit(None), None, 2.6),
        PhotoResult("moge-2-l", "a.jpg", 6.0, _fit(2.65), None, 2.7),
    ]


def test_ceiling_error_is_a_percentage_of_the_measured_height() -> None:
    assert _results()[1].ceiling_error_pct == pytest.approx(20.0)
    assert _results()[2].ceiling_error_pct is None
    assert _results()[3].ceiling_error_pct is None


def test_summary_counts_per_model() -> None:
    s, big = summarize(_results())
    assert (s.model, big.model) == ("moge-2-s", "moge-2-l")
    assert s.photos == 4
    assert s.floor_found == 3
    assert s.compared == 2
    assert s.mean_error_pct == pytest.approx(10.0)
    assert s.max_error_pct == pytest.approx(20.0)
    assert s.within_10pct == 1
    assert s.ceiling_unknown == 1
    assert s.mean_seconds == pytest.approx(3.0)
    assert big.compared == 1


def test_summary_without_any_measured_height_has_no_error() -> None:
    (s,) = summarize([PhotoResult("m", "a.jpg", 1.0, _fit(2.7), None, None)])
    assert s.compared == 0
    assert s.mean_error_pct is None
    assert s.max_error_pct is None


def test_report_lists_every_model_and_photo() -> None:
    results = _results()
    text = render_markdown(summarize(results), results)
    for name in ("moge-2-s", "moge-2-l", "a.jpg", "b.jpg", "c.jpg", "d.jpg", "看不到地板"):
        assert name in text
