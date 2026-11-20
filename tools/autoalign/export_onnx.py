"""把 MoGe-2 小版轉成瀏覽器能跑的 ONNX（半精度，約 71 MB）。

給網頁版 AI 對齊用（docs/web-align.md）。

只包模型的 forward（照片大小、token 數都可以變）；後處理在 prototype/webalign.js。
轉完會用 onnxruntime 跟 PyTorch 比對同一張圖的輸出，差太多就失敗。

用法（在 tools/autoalign 底下）：
    .venv/Scripts/python.exe export_onnx.py
輸出：prototype/models/moge-2-s-fp16.onnx（不進 git）
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from moge.model.v2 import MoGeModel
from onnxruntime.transformers.float16 import convert_float_to_float16

REPO = "Ruicheng/moge-2-vits-normal"
OUT = Path(__file__).resolve().parents[2] / "prototype" / "models" / "moge-2-s-fp16.onnx"
OUTPUTS = ["points", "normal", "mask", "metric_scale"]
MAX_DIFF_FP32 = 1e-3  # ONNX（全精度）跟 PyTorch 的最大差
MAX_DIFF_FP16 = 0.05  # 半精度（真的要給網頁用的那個檔）跟 PyTorch 的最大差


class Forward(torch.nn.Module):
    def __init__(self, model: MoGeModel) -> None:
        super().__init__()
        self.model = model

    def forward(self, image: torch.Tensor, num_tokens: torch.Tensor) -> tuple[torch.Tensor, ...]:
        out = self.model(image, num_tokens=num_tokens)
        return tuple(out[k] for k in OUTPUTS)


def export_fp32(wrapper: Forward, path: Path) -> None:
    hw = {2: "height", 3: "width"}
    out_hw = {1: "height", 2: "width"}
    torch.onnx.export(
        wrapper,
        (torch.rand(1, 3, 588, 784), torch.tensor(2400, dtype=torch.int64)),
        str(path),
        input_names=["image", "num_tokens"],
        output_names=OUTPUTS,
        dynamic_axes={"image": hw, "points": out_hw, "normal": out_hw, "mask": out_hw},
        opset_version=17,
        dynamo=False,
    )


def check(wrapper: Forward, path: Path) -> float:
    """同一張亂數圖，ONNX 跟 PyTorch 的輸出最大差多少（直的、橫的各一張）。

    有任何 NaN 或無限大就回傳 inf（np.max 遇到 NaN 會是 NaN，跟上限比較永遠不會失敗）。
    """
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    worst = 0.0
    for h, w, n in [(588, 784, 2400), (784, 588, 2400), (420, 560, 1200)]:
        x = torch.rand(1, 3, h, w)
        with torch.inference_mode():
            ref = wrapper(x, torch.tensor(n))
        feeds = {"image": x.numpy(), "num_tokens": np.array(n, dtype=np.int64)}
        got = sess.run(None, feeds)
        for g, r in zip(got, ref, strict=True):
            if not (np.all(np.isfinite(g)) and np.all(np.isfinite(r.numpy()))):
                return float("inf")
            worst = max(worst, float(np.max(np.abs(g - r.numpy()))))
    return worst


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    model = MoGeModel.from_pretrained(REPO).eval()
    model.onnx_compatible_mode = True  # 不用 antialias、位置編碼用固定大小：ONNX 才轉得出來
    wrapper = Forward(model).eval()
    with tempfile.TemporaryDirectory() as tmp:
        fp32 = Path(tmp) / "fp32.onnx"
        export_fp32(wrapper, fp32)
        diff = check(wrapper, fp32)
        print(f"ONNX 跟 PyTorch 最大差：{diff:.2e}")
        if not diff <= MAX_DIFF_FP32:
            print(f"差太多（上限 {MAX_DIFF_FP32}），不輸出")
            return 1
        half = convert_float_to_float16(onnx.load(str(fp32)), keep_io_types=True)
        fp16 = Path(tmp) / "fp16.onnx"
        onnx.save(half, str(fp16))
        diff16 = check(wrapper, fp16)  # 真的要交出去的是這個檔：也要過關
        print(f"半精度跟 PyTorch 最大差：{diff16:.2e}")
        if not diff16 <= MAX_DIFF_FP16:
            print(f"半精度差太多（上限 {MAX_DIFF_FP16}），不輸出")
            return 1
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(fp16.read_bytes())
    print(f"寫好了：{args.out}（{args.out.stat().st_size / 1e6:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
