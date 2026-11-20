"""AI 深度模型的轉接頭。

每個模型都變成同一個樣子：照片 (列, 欄, 3) uint8 → OpenCV 鏡頭座標的點 (列, 欄, 3) 和 fy（像素）。
沒有深度的點填 NaN。
"""

from __future__ import annotations

import numpy as np
import torch
from moge.model.v2 import MoGeModel

MOGE_REPOS = {
    "moge-2-s": "Ruicheng/moge-2-vits-normal",  # 141 MB，MIT
    "moge-2-l": "Ruicheng/moge-2-vitl-normal",  # 1.3 GB，MIT
}


class MogeDepth:
    def __init__(self, repo: str) -> None:
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = MoGeModel.from_pretrained(repo).to(self.device).eval()

    def __call__(self, rgb: np.ndarray) -> tuple[np.ndarray, float]:
        image = torch.tensor(rgb / 255, dtype=torch.float32, device=self.device).permute(2, 0, 1)
        with torch.inference_mode():
            out = self.model.infer(image)
        points = out["points"].cpu().numpy().astype(np.float64)
        points[~out["mask"].cpu().numpy().astype(bool)] = np.nan
        # MoGe 的 intrinsics 是除以圖片寬高的；fy 乘回列數變成像素
        fy = float(out["intrinsics"][1, 1]) * rgb.shape[0]
        return points, fy


def load_model(name: str) -> MogeDepth:
    if name not in MOGE_REPOS:
        raise ValueError(f"不認得的模型：{name}。可以用：{', '.join(MOGE_REPOS)}")
    return MogeDepth(MOGE_REPOS[name])
