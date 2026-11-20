"""產生網頁版（prototype/webalign.js）對照用的答案：同樣的輸入，Python 算出來是多少。

1. fit：假房間的幾個場景（JS 那邊用同一個假房間自己畫），Python fit_camera 的結果
2. postprocess：一份假的模型輸出，跑 MoGe 原本的 infer 後處理 + fit_camera 的結果

用法（在 tools/autoalign 底下）：.venv/Scripts/python.exe make_web_fixtures.py
不用照片，也不寫任何影像。
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
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
)

from geometry import NoFloorError, fit_camera

OUT = (
    Path(__file__).resolve().parents[2] / "prototype" / "tests" / "fixtures" / "python_parity.json"
)

SHOTS = {
    "clean": Shot(),
    "tilted": Shot(height=1.6, pitch=15.0, roll=-4.0, vfov=65.0, ceiling=2.9),
    "sofa_table": Shot(boxes=(SOFA, SIDE_TABLE)),
    "platform": Shot(boxes=(LOW_PLATFORM,)),
    "bedroom": Shot(height=1.6, pitch=20.0, vfov=65.0, width=120, rows=160, boxes=(BED,)),
    "futon": Shot(height=0.87, pitch=-5.0, vfov=67.0, width=120, rows=160, boxes=(FUTON,)),
    "no_ceiling": Shot(pitch=35.0, vfov=45.0),
    "walls_above": Shot(pitch=5.0, vfov=26.0),
    "two_level_ceiling": Shot(pitch=-5.0, vfov=65.0, ceiling=3.0, boxes=(SOFFIT,)),
    "upper_cabinet": Shot(pitch=5.0, vfov=26.0, boxes=(UPPER_CABINET,)),
}
BOX_NAMES = {
    id(b): n
    for n, b in [
        ("SOFA", SOFA),
        ("SIDE_TABLE", SIDE_TABLE),
        ("LOW_PLATFORM", LOW_PLATFORM),
        ("BED", BED),
        ("FUTON", FUTON),
        ("SOFFIT", SOFFIT),
        ("UPPER_CABINET", UPPER_CABINET),
    ]
}


def fit_dict(points: np.ndarray, fy: float) -> dict:
    try:
        f = fit_camera(points, fy, rng=np.random.default_rng(0))
    except NoFloorError as e:
        return {"error": str(e)}
    return {k: v for k, v in asdict(f).items() if k != "floor_inlier_ratio"}


def shot_dict(shot: Shot) -> dict:
    d = asdict(replace(shot, boxes=()))
    d["boxes"] = [BOX_NAMES[id(b)] for b in shot.boxes]
    return d


def fake_model_output(shot: Shot, shift: float, scale: float, seed: int) -> dict:
    """真實的點 = (模型輸出 + (0, 0, shift)) 乘 scale。有 5% 的點模型說「沒有深度」。"""
    points, _ = render(shot)
    raw = points / scale
    raw[..., 2] -= shift
    rng = np.random.default_rng(seed)
    mask = np.where(rng.random(points.shape[:2]) < 0.05, 0.1, 0.9)
    raw[mask < 0.5] = 0.0
    return {"raw": raw.astype(np.float32), "mask": mask.astype(np.float32), "scale": scale}


def moge_postprocess(out: dict) -> tuple[np.ndarray, float, torch.Tensor]:
    """把假的輸出餵給 MoGe 原本的 infer（換掉 forward），拿它的後處理結果。"""
    from moge.model.v2 import MoGeModel

    model = MoGeModel.from_pretrained("Ruicheng/moge-2-vits-normal").eval()
    rows, cols = out["mask"].shape
    model.forward = lambda image, num_tokens: {
        "points": torch.from_numpy(out["raw"])[None],
        "normal": torch.zeros(1, rows, cols, 3),
        "mask": torch.from_numpy(out["mask"])[None],
        "metric_scale": torch.tensor([out["scale"]]),
    }
    with torch.inference_mode():
        res = model.infer(torch.zeros(3, rows, cols), use_fp16=False)
    points = res["points"].numpy().astype(np.float64)
    points[~res["mask"].numpy()] = np.nan
    return points, float(res["intrinsics"][1, 1]) * rows, res["intrinsics"]


def main() -> None:
    fits = {
        name: {"shot": shot_dict(s), "expected": fit_dict(*render(s))} for name, s in SHOTS.items()
    }

    shot = Shot(width=96, rows=72)
    out = fake_model_output(shot, shift=0.6, scale=1.7, seed=7)
    points, fy, intrinsics = moge_postprocess(out)
    samples = [
        int(i) for i in np.random.default_rng(1).choice(shot.rows * shot.width, 12, replace=False)
    ]
    flat = points.reshape(-1, 3)
    post = {
        "shot": shot_dict(shot),
        "rows": shot.rows,
        "cols": shot.width,
        "raw": [round(float(v), 6) for v in out["raw"].ravel()],
        "mask": [round(float(v), 3) for v in out["mask"].ravel()],
        "metric_scale": out["scale"],
        "expected": {
            "fx": float(intrinsics[0, 0]),
            "fy": float(intrinsics[1, 1]),
            "fy_px": fy,
            "samples": {
                str(i): [None if not np.isfinite(v) else float(v) for v in flat[i]] for i in samples
            },
            "fit": fit_dict(points, fy),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"fit": fits, "postprocess": post}, ensure_ascii=False), encoding="utf-8"
    )
    print(f"寫好了：{OUT}（{OUT.stat().st_size // 1024} KB）")


if __name__ == "__main__":
    main()
