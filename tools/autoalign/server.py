"""本機對齊服務：原型上傳照片 → 這裡跑 AI → 回傳 5 個滑桿的值。

只聽 127.0.0.1（只有這台電腦連得到）。照片只在記憶體裡處理，不寫進硬碟。
同時提供原型網頁和燈具目錄（prototype/ 裡的白名單檔案），所以打開 http://127.0.0.1:5191 就能用。

預設用小版模型（141 MB）：顯示卡被別的 AI 程式佔住時，大版（1.3 GB）可能載不起來。

用法（在 tools/autoalign 底下）：
    .venv/Scripts/python.exe server.py
    .venv/Scripts/python.exe server.py --model moge-2-l --port 5191
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from evaluate import MAX_EDGE_PX, DepthModel
from geometry import NoFloorError, fit_camera
from occlusion import occluder_depth_mm

HOST = "127.0.0.1"
DEFAULT_PORT = 5191
MAX_BYTES = 20 * 1024 * 1024  # 規格：照片超過 20 MB 不處理
READ_TIMEOUT_S = 10.0  # 上傳卡住超過這麼久就斷線，服務才不會被一個請求卡死
SITE = Path(__file__).resolve().parents[2] / "prototype"
# 只給這幾個檔案（白名單）：照片、測試、其他檔案都拿不到
SITE_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/lamps.js": "lamps.js",
    "/catalog.js": "catalog.js",  # 爬到的燈（export_catalog.py 產生）
    "/erase.js": "erase.js",  # 擦掉照片裡的東西（docs/erase.md）
    "/models/mobile_sam_image_encoder.onnx": "models/mobile_sam_image_encoder.onnx",
    "/models/sam_mask_decoder_single.onnx": "models/sam_mask_decoder_single.onnx",
    "/models/migan_pipeline_v2.onnx": "models/migan_pipeline_v2.onnx",
    "/webalign.js": "webalign.js",
    "/models/moge-2-s-fp16.onnx": "models/moge-2-s-fp16.onnx",  # 網頁版 AI（export_onnx.py 產生）
}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".onnx": "application/octet-stream",
}


class BadPhotoError(ValueError):
    """收到的東西不是照片，或照片大到不能處理。"""


def content_length(value: str | None) -> int | None:
    """Content-Length 的值：沒寫當 0；不是 0 以上的整數（例如 -1、abc）回傳 None。"""
    text = (value or "0").strip()
    return int(text) if text.isascii() and text.isdigit() else None


def decode_photo(data: bytes) -> np.ndarray:
    """照片的位元組 → (列, 欄, 3) uint8。照手機記錄的方向轉正，最長邊縮到 MAX_EDGE_PX。"""
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Image.DecompressionBombError as e:
        raise BadPhotoError("照片太大（像素太多）") from e
    except (UnidentifiedImageError, OSError) as e:
        raise BadPhotoError("只支援照片：JPG、PNG 或 WebP") from e
    image.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX))
    return np.asarray(image)


def align(model: DepthModel, rgb: np.ndarray) -> dict[str, object]:
    """跑 AI 和幾何計算，回傳原型 5 個滑桿要的值，加上遮擋用的深度圖。

    看不到天花板時 ceiling_m 是 None。深度圖：mm 是 base64 的 uint16（little-endian），
    一列一列從照片最上面排下來；0 代表不擋東西（地板、天花板、沒有深度）。
    """
    points, fy = model(rgb)
    fit = fit_camera(points, fy)
    depth = occluder_depth_mm(points, fit)
    return {
        "height_m": fit.height_m,
        "pitch_deg": fit.pitch_deg,
        "roll_deg": fit.roll_deg,
        "vfov_deg": fit.vfov_deg,
        "ceiling_m": fit.ceiling_m,
        "depth": {
            "width": depth.shape[1],
            "height": depth.shape[0],
            "mm": base64.b64encode(depth.astype("<u2").tobytes()).decode("ascii"),
        },
    }


class AlignHandler(BaseHTTPRequestHandler):
    """GET 給原型網頁和燈具目錄；POST /api/align 收照片、回傳滑桿的值。

    用 make_server 綁上模型和網頁資料夾。
    """

    model: DepthModel
    site: Path
    max_bytes: int = MAX_BYTES
    timeout: float = READ_TIMEOUT_S  # 讀取逾時（StreamRequestHandler 會套到連線上）

    def do_GET(self) -> None:
        file = self._site_file()
        if file is not None:
            self._send(200, CONTENT_TYPES[file.suffix], file.read_bytes())

    def do_HEAD(self) -> None:
        """只回大小（網頁版用它問「模型在不在」，不用真的下載）。"""
        file = self._site_file()
        if file is not None:
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES[file.suffix])
            self.send_header("Content-Length", str(file.stat().st_size))
            self.end_headers()

    def _site_file(self) -> Path | None:
        """白名單上、而且真的存在的檔案；不是的話回 404 並傳回 None。"""
        name = SITE_FILES.get(self.path.split("?")[0])
        file = self.site / name if name else None
        if file is None or not file.is_file():  # 模型還沒用 export_onnx.py 做出來時也是找不到
            self._json(404, {"error": "找不到"})
            return None
        return file

    def do_POST(self) -> None:
        if self.path != "/api/align":
            self._json(404, {"error": "找不到"})
            return
        data = self._read_body()
        if data is not None:
            self._align(data)

    def _read_body(self) -> bytes | None:
        size = content_length(self.headers.get("Content-Length"))
        if size is None:
            self.close_connection = True
            self._json(400, {"error": "上傳的照片大小不對（Content-Length）"})
            return None
        if size > self.max_bytes:
            self.close_connection = True
            self._json(413, {"error": "照片太大（上限 20 MB）"})
            return None
        return self.rfile.read(size)

    def _align(self, data: bytes) -> None:
        try:
            self._json(200, align(self.model, decode_photo(data)))
        except BadPhotoError as e:
            self._json(400, {"error": str(e)})
        except NoFloorError as e:
            self._json(422, {"error": f"AI 找不到地板，請用滑桿手動對齊。（{e}）"})

    def _json(self, status: int, body: dict) -> None:
        text = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", text)

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":  # HEAD 只回標頭，連錯誤訊息也不送
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """不印每個請求，終端機才不會被洗版。"""


def make_server(
    model: DepthModel,
    site: Path,
    *,
    port: int = DEFAULT_PORT,
    max_bytes: int = MAX_BYTES,
    timeout: float = READ_TIMEOUT_S,
) -> HTTPServer:
    """site：放 index.html 和 lamps.js 的資料夾（平常是 prototype/）。"""
    # staticmethod：模型如果是普通函式，放在類別上會被當成方法，多收一個 self
    bound = {"model": staticmethod(model), "site": site, "max_bytes": max_bytes, "timeout": timeout}
    return HTTPServer((HOST, port), type("BoundAlignHandler", (AlignHandler,), bound))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="moge-2-s", choices=["moge-2-s", "moge-2-l"])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    # Windows 中文版的終端機預設 cp950，印不出部分符號
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from models import load_model  # 要 torch，測試時不載入

    print(f"載入 {args.model}……", flush=True)
    try:
        model = load_model(args.model)
        model(np.zeros((480, 640, 3), np.uint8))  # 暖機：第一次跑比較慢
    except RuntimeError as e:  # 顯示卡記憶體不夠時，torch 丟的是 RuntimeError
        print(f"AI 模型載不起來：{e}")
        print("通常是顯示卡記憶體被別的程式佔住。關掉別的 AI 程式再試，或改用小版 --model moge-2-s")
        return 1
    server = make_server(model, SITE, port=args.port)
    print(f"對齊服務開好了：http://{HOST}:{args.port}　（按 Ctrl+C 關掉）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
