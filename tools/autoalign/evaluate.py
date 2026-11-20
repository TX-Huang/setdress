"""用真的照片測 AI 自動對齊：每張照片跑每個模型，畫格線圖，跟捲尺量的天花板高度比。

用法（在 tools/autoalign 底下）：
    .venv/Scripts/python.exe evaluate.py --photos photos --out out --models moge-2-s moge-2-l

photos/ceilings.csv 放捲尺量的天花板高度（公尺）。第一行是標題；「*」那行套用到沒有單獨寫的照片：
    photo,ceiling_m
    *,2.8
    bedroom.jpg,2.65
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from geometry import CameraFit, NoFloorError, fit_camera
from overlay import draw_grid

PASS_PCT = 10.0  # 規格：天花板誤差 ≤ 10%
MIN_ROOM_M = 1.8
MAX_ROOM_M = 6.0
PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_EDGE_PX = 1600

DepthModel = Callable[[np.ndarray], tuple[np.ndarray, float]]


@dataclass(frozen=True)
class PhotoResult:
    model: str
    photo: str
    seconds: float
    fit: CameraFit | None
    error: str | None
    truth_m: float | None

    @property
    def ceiling_error_pct(self) -> float | None:
        if self.fit is None or self.fit.ceiling_m is None or self.truth_m is None:
            return None
        return abs(self.fit.ceiling_m - self.truth_m) / self.truth_m * 100


@dataclass(frozen=True)
class ModelSummary:
    model: str
    photos: int
    floor_found: int
    compared: int
    mean_error_pct: float | None
    max_error_pct: float | None
    within_10pct: int
    ceiling_unknown: int
    mean_seconds: float


# ---------- 天花板實量值 ----------


def load_truth(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    truth: dict[str, float] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for line_no, row in enumerate(reader, start=2):
            if row and row[0].strip():
                truth[row[0].strip()] = _height(row, line_no)
    return truth


def _height(row: list[str], line_no: int) -> float:
    try:
        value = float(row[1])
    except (IndexError, ValueError):
        raise ValueError(
            f"ceilings.csv 第 {line_no} 行：天花板高度要是數字（公尺），例如 2.75"
        ) from None
    if not MIN_ROOM_M <= value <= MAX_ROOM_M:
        raise ValueError(
            f"ceilings.csv 第 {line_no} 行：{value} 不像天花板高度。請用公尺，例如 2.75，不是 275"
        )
    return value


def truth_for(truth: dict[str, float], photo: str) -> float | None:
    return truth.get(photo, truth.get("*"))


# ---------- 整理結果 ----------


def summarize(results: list[PhotoResult]) -> list[ModelSummary]:
    by_model: dict[str, list[PhotoResult]] = {}
    for r in results:
        by_model.setdefault(r.model, []).append(r)
    return [_summary(model, rows) for model, rows in by_model.items()]


def _summary(model: str, rows: list[PhotoResult]) -> ModelSummary:
    errors = [e for e in (r.ceiling_error_pct for r in rows) if e is not None]
    found = [r.fit for r in rows if r.fit is not None]
    unknown = sum(
        1 for r in rows if r.fit is not None and r.fit.ceiling_m is None and r.truth_m is not None
    )
    return ModelSummary(
        model=model,
        photos=len(rows),
        floor_found=len(found),
        compared=len(errors),
        mean_error_pct=sum(errors) / len(errors) if errors else None,
        max_error_pct=max(errors, default=None),
        within_10pct=sum(e <= PASS_PCT for e in errors),
        ceiling_unknown=unknown,
        mean_seconds=sum(r.seconds for r in rows) / len(rows),
    )


def _fmt(value: float | None, pattern: str) -> str:
    return "—" if value is None else pattern.format(value)


def _summary_row(s: ModelSummary) -> str:
    cells = [
        s.model,
        str(s.photos),
        str(s.floor_found),
        str(s.compared),
        _fmt(s.mean_error_pct, "{:.1f}%"),
        _fmt(s.max_error_pct, "{:.1f}%"),
        f"{s.within_10pct} / {s.compared}",
        str(s.ceiling_unknown),
        f"{s.mean_seconds:.1f}",
    ]
    return "| " + " | ".join(cells) + " |"


def _photo_row(r: PhotoResult) -> str:
    f = r.fit
    cells = [
        r.photo,
        r.model,
        _fmt(f and f.height_m, "{:.2f} m"),
        _fmt(f and f.pitch_deg, "{:.1f}°"),
        _fmt(f and f.roll_deg, "{:.1f}°"),
        _fmt(f and f.vfov_deg, "{:.1f}°"),
        _fmt(f and f.ceiling_m, "{:.2f} m"),
        _fmt(r.truth_m, "{:.2f} m"),
        _fmt(r.ceiling_error_pct, "{:.1f}%"),
        r.error or "",
    ]
    return "| " + " | ".join(cells) + " |"


def render_markdown(summaries: list[ModelSummary], results: list[PhotoResult]) -> str:
    lines = [
        "# AI 自動對齊：真實照片測試結果",
        "",
        f"過關標準：天花板誤差 ≤ {PASS_PCT:.0f}%；"
        "格線要貼齊地板（看 out/<模型>/ 裡的圖，用眼睛判斷）。",
        "",
        "## 各模型",
        "",
        "| 模型 | 照片 | 找到地板 | 有實量可比 | 天花板誤差（平均） | 最大誤差 | ≤ 10% | "
        "有實量但看不到天花板 | 每張秒數 |",
        "|---|---|---|---|---|---|---|---|---|",
        *(_summary_row(s) for s in summaries),
        "",
        "## 每張照片",
        "",
        "| 照片 | 模型 | 鏡頭離地 | 往下看 | 歪斜 | 視角 | "
        "天花板（算） | 天花板（量） | 誤差 | 備註 |",
        "|---|---|---|---|---|---|---|---|---|---|",
        *(_photo_row(r) for r in results),
        "",
    ]
    return "\n".join(lines)


# ---------- 跑模型 ----------


def _load(photo: Path) -> Image.Image:
    image = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    image.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX))
    return image


def _run_one(
    model: DepthModel, name: str, photo: Path, truth: dict[str, float], out: Path
) -> PhotoResult:
    image = _load(photo)
    start = time.perf_counter()
    points, fy = model(np.asarray(image))
    try:
        fit, error = fit_camera(points, fy), None
    except NoFloorError as e:
        fit, error = None, str(e)
    seconds = time.perf_counter() - start
    if fit is not None:
        draw_grid(image, fit, points).save(out / name / f"{photo.stem}.jpg", quality=90)
    return PhotoResult(name, photo.name, seconds, fit, error, truth_for(truth, photo.name))


def _write_csv(results: list[PhotoResult], path: Path) -> None:
    fields = ["model", "photo", "seconds", "height_m", "pitch_deg", "roll_deg", "vfov_deg"]
    fields += ["ceiling_m", "truth_m", "ceiling_error_pct", "error"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(fields)
        for r in results:
            fit = r.fit
            values = (
                [fit.height_m, fit.pitch_deg, fit.roll_deg, fit.vfov_deg, fit.ceiling_m]
                if fit
                else [None] * 5
            )
            writer.writerow(
                [
                    r.model,
                    r.photo,
                    f"{r.seconds:.2f}",
                    *values,
                    r.truth_m,
                    r.ceiling_error_pct,
                    r.error or "",
                ]
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--photos", type=Path, default=Path("photos"))
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--models", nargs="+", default=["moge-2-s", "moge-2-l"])
    args = parser.parse_args(argv)

    photos = sorted(p for p in args.photos.iterdir() if p.suffix.lower() in PHOTO_TYPES)
    if not photos:
        print(f"{args.photos} 裡沒有照片（支援 JPG、PNG、WebP）")
        return 1
    truth = load_truth(args.photos / "ceilings.csv")

    from models import load_model  # 要 torch，測試時不載入

    results: list[PhotoResult] = []
    for name in args.models:
        (args.out / name).mkdir(parents=True, exist_ok=True)
        model = load_model(name)
        model(np.asarray(_load(photos[0])))  # 暖機：第一次跑比較慢，不算進時間
        results += [_run_one(model, name, p, truth, args.out) for p in photos]

    report = render_markdown(summarize(results), results)
    (args.out / "summary.md").write_text(report, encoding="utf-8")
    _write_csv(results, args.out / "results.csv")
    # Windows 中文版的終端機預設 cp950，印不出「≤」這類符號
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
