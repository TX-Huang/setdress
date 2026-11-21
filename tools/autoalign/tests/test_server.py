"""本機對齊服務：用假的深度模型（直接回傳假房間的點），不用載入真的 AI。"""

from __future__ import annotations

import base64
import http.client
import io
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from synthetic_room import Shot, render

from server import make_server

SHOT = Shot(height=1.4, pitch=12.0, roll=2.0, vfov=60.0, ceiling=2.8)
NO_CEILING = Shot(pitch=35.0, vfov=45.0)
NO_FLOOR = Shot(pitch=-12.0, vfov=30.0)


def _photo(fmt: str = "JPEG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (180, 170, 160)).save(buf, fmt)
    return buf.getvalue()


class FakeModel:
    """不管照片是什麼，都回傳某個假房間的點；記下收到的照片大小。"""

    def __init__(self, shot: Shot) -> None:
        self.shot = shot
        self.seen: list[tuple[int, ...]] = []

    def __call__(self, rgb: np.ndarray) -> tuple[np.ndarray, float]:
        self.seen.append(rgb.shape)
        return render(self.shot)


# 擦掉照片裡的東西用的模型（docs/erase.md）
ERASE_MODELS = (
    "mobile_sam_image_encoder.onnx",
    "sam_mask_decoder_single.onnx",
    "migan_pipeline_v2.onnx",
)


@pytest.fixture
def site(tmp_path: Path) -> Path:
    """假的 prototype 資料夾：網頁、燈具目錄，加一個不該被看到的檔案。"""
    folder = tmp_path / "prototype"
    folder.mkdir()
    (folder / "index.html").write_text("<title>Setdress 原型</title>", encoding="utf-8")
    (folder / "lamps.js").write_text("// 燈具目錄 LAMPS", encoding="utf-8")
    (folder / "catalog.js").write_text("// 爬到的燈 SetdressCatalog", encoding="utf-8")
    (folder / "erase.js").write_text("// 擦掉 SetdressErase", encoding="utf-8")
    (folder / "decor.js").write_text("// 擺飾 SetdressDecor", encoding="utf-8")
    (folder / "rugs.js").write_text("// 地毯 SetdressRugs", encoding="utf-8")
    (folder / "goods.js").write_text("// 全部商品 SetdressGoods", encoding="utf-8")
    (folder / "cutout.js").write_text("// 去背 SetdressCutout", encoding="utf-8")
    (folder / "goods").mkdir()
    (folder / "goods" / "index.json").write_text('{"groups": []}', encoding="utf-8")
    (folder / "goods" / "lamp-pendant.json").write_text('{"items": []}', encoding="utf-8")
    (folder / "goods" / "notes.txt").write_text("不要給別人看", encoding="utf-8")
    (folder / "models3d").mkdir()
    (folder / "models3d" / "index.json").write_text('{"models": {}}', encoding="utf-8")
    (folder / "models3d" / "0a1b2c3d4e5f6789.glb").write_bytes(b"glTF-fake")
    (folder / "notes.txt").write_text("不要給別人看", encoding="utf-8")
    (folder / "webalign.js").write_text("// 網頁版對齊 SetdressAlign", encoding="utf-8")
    (folder / "models").mkdir()
    (folder / "models" / "moge-2-s-fp16.onnx").write_bytes(b"fake-onnx")
    for name in ERASE_MODELS:
        (folder / "models" / name).write_bytes(b"fake-" + name.encode())
    return folder


def _serve(model: FakeModel, site: Path, **kwargs: float) -> Iterator[str]:
    server = make_server(model, site, port=0, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def url(site: Path) -> Iterator[str]:
    yield from _serve(FakeModel(SHOT), site)


def _post(url: str, body: bytes) -> tuple[int, dict]:
    req = urllib.request.Request(
        url + "/api/align", data=body, method="POST", headers={"Content-Type": "image/jpeg"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_photo_gives_the_five_slider_values(url: str) -> None:
    status, body = _post(url, _photo())
    assert status == 200
    assert body["height_m"] == pytest.approx(SHOT.height, abs=0.01)
    assert body["pitch_deg"] == pytest.approx(SHOT.pitch, abs=0.5)
    assert body["roll_deg"] == pytest.approx(SHOT.roll, abs=0.5)
    assert body["vfov_deg"] == pytest.approx(SHOT.vfov, abs=0.5)
    assert body["ceiling_m"] == pytest.approx(SHOT.ceiling, abs=0.02)


def test_photo_comes_back_with_a_depth_map_for_occlusion(url: str) -> None:
    status, body = _post(url, _photo())
    assert status == 200
    depth = body["depth"]
    assert (depth["width"], depth["height"]) == (SHOT.width, SHOT.rows)
    mm = np.frombuffer(base64.b64decode(depth["mm"]), dtype="<u2")
    assert mm.size == SHOT.width * SHOT.rows
    assert 0 < mm.max() < 10_000


def test_png_works_too(url: str) -> None:
    status, _ = _post(url, _photo("PNG"))
    assert status == 200


def test_ceiling_out_of_view_is_null(site: Path) -> None:
    for url in _serve(FakeModel(NO_CEILING), site):
        status, body = _post(url, _photo())
        assert status == 200
        assert body["ceiling_m"] is None
        assert body["height_m"] == pytest.approx(NO_CEILING.height, abs=0.01)


def test_no_floor_says_so(site: Path) -> None:
    for url in _serve(FakeModel(NO_FLOOR), site):
        status, body = _post(url, _photo())
        assert status == 422
        assert "地板" in body["error"]


def test_not_a_photo_is_rejected(url: str) -> None:
    status, body = _post(url, b"this is not a photo")
    assert status == 400
    assert "只支援照片" in body["error"]


def test_empty_body_is_rejected(url: str) -> None:
    status, body = _post(url, b"")
    assert status == 400
    assert "只支援照片" in body["error"]


def test_too_large_photo_is_rejected_before_running_the_model(site: Path) -> None:
    model = FakeModel(SHOT)
    for url in _serve(model, site, max_bytes=100):
        status, body = _post(url, _photo())
        assert status == 413
        assert "太大" in body["error"]
    assert model.seen == []


def _post_with_length(url: str, length: str) -> tuple[int, dict]:
    """自己寫 Content-Length（urllib 會幫你算對，測不到壞的值）。"""
    host, port = url.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    try:
        conn.putrequest("POST", "/api/align")
        conn.putheader("Content-Length", length)
        conn.endheaders()
        res = conn.getresponse()
        return res.status, json.loads(res.read())
    finally:
        conn.close()


@pytest.mark.parametrize("length", ["-1", "abc", ""])
def test_bad_content_length_is_rejected_before_reading(site: Path, length: str) -> None:
    model = FakeModel(SHOT)
    for url in _serve(model, site):
        status, body = _post_with_length(url, length)
    assert status == 400
    assert "照片" in body["error"]
    assert model.seen == []


def test_unfinished_upload_does_not_block_the_service(site: Path) -> None:
    for url in _serve(FakeModel(SHOT), site, timeout=0.5):
        host, port = url.removeprefix("http://").split(":")
        stuck = socket.create_connection((host, int(port)))
        try:
            # 說要送 100 bytes，只送 5 個，連線也不關
            head = b"POST /api/align HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n"
            stuck.sendall(head + b"12345")
            start = time.monotonic()
            status, _ = _post(url, _photo())
            assert status == 200
            assert time.monotonic() - start < 5
        finally:
            stuck.close()


def test_big_photo_is_shrunk_before_the_model(site: Path) -> None:
    model = FakeModel(SHOT)
    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), (120, 120, 120)).save(buf, "JPEG")
    for url in _serve(model, site):
        status, _ = _post(url, buf.getvalue())
        assert status == 200
    assert max(model.seen[0][:2]) == 1600


def test_photo_is_not_written_to_disk(
    url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    status, _ = _post(url, _photo())
    assert status == 200
    assert list(work.iterdir()) == []


def test_serves_the_prototype_page(url: str) -> None:
    with urllib.request.urlopen(url + "/", timeout=10) as res:
        assert res.status == 200
        assert "text/html" in res.headers["Content-Type"]
        assert "Setdress 原型" in res.read().decode("utf-8")


def test_serves_the_lamp_catalog(url: str) -> None:
    with urllib.request.urlopen(url + "/lamps.js", timeout=10) as res:
        assert res.status == 200
        assert "javascript" in res.headers["Content-Type"]
        assert "LAMPS" in res.read().decode("utf-8")


def test_serves_the_crawled_lamp_catalog(url: str) -> None:
    # 爬到的燈（docs/catalog.md 第 14 句）：本機的服務也要給
    with urllib.request.urlopen(url + "/catalog.js", timeout=10) as res:
        assert res.status == 200
        assert "javascript" in res.headers["Content-Type"]
        assert "SetdressCatalog" in res.read().decode("utf-8")


def test_serves_the_rugs(url: str) -> None:
    with urllib.request.urlopen(url + "/rugs.js", timeout=10) as res:  # docs/rugs.md
        assert "SetdressRugs" in res.read().decode("utf-8")


def test_serves_every_goods_file(url: str) -> None:
    """全部商品（docs/goods.md）：一類一個 JSON，檔名不固定，整個資料夾的 .json 都給。"""
    for path, text in [
        ("/goods.js", "SetdressGoods"),
        ("/cutout.js", "SetdressCutout"),
        ("/goods/index.json", "groups"),
        ("/goods/lamp-pendant.json", "items"),
    ]:
        with urllib.request.urlopen(url + path, timeout=10) as res:
            assert text in res.read().decode("utf-8"), path
            if path.endswith(".json"):
                assert res.headers["Content-Type"].startswith("application/json")


def test_serves_the_ai_3d_models(url: str) -> None:
    """AI 生的 3D（docs/model3d.md）：models3d 資料夾裡的 .glb 和 index.json。"""
    with urllib.request.urlopen(url + "/models3d/index.json", timeout=10) as res:
        assert "models" in res.read().decode("utf-8")
    with urllib.request.urlopen(url + "/models3d/0a1b2c3d4e5f6789.glb", timeout=10) as res:
        assert res.read() == b"glTF-fake"
        assert res.headers["Content-Type"] == "model/gltf-binary"


@pytest.mark.parametrize(
    "path",
    [
        "/goods/notes.txt",
        "/goods/../notes.txt",
        "/goods/%2e%2e/notes.txt",
        "/goods/x.glb",
        "/models3d/x.txt",
    ],
)
def test_only_json_in_the_goods_folder(url: str, path: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(url + path, timeout=10)
    assert err.value.code == 404


def test_serves_the_decor_items(url: str) -> None:
    # 擺飾：花瓶、花器（docs/decor.md 第 9 句）
    with urllib.request.urlopen(url + "/decor.js", timeout=10) as res:
        assert "SetdressDecor" in res.read().decode("utf-8")


def test_serves_the_erase_tool_and_its_models(url: str) -> None:
    # 擦掉照片裡的東西（docs/erase.md）：本機打開也是瀏覽器在算，要給程式和模型
    with urllib.request.urlopen(url + "/erase.js", timeout=10) as res:
        assert "SetdressErase" in res.read().decode("utf-8")
    for name in ERASE_MODELS:
        with urllib.request.urlopen(url + "/models/" + name, timeout=10) as res:
            assert res.read() == b"fake-" + name.encode()


def test_serves_the_web_align_script_and_model(url: str) -> None:
    with urllib.request.urlopen(url + "/webalign.js", timeout=10) as res:
        assert "javascript" in res.headers["Content-Type"]
        assert "SetdressAlign" in res.read().decode("utf-8")
    with urllib.request.urlopen(url + "/models/moge-2-s-fp16.onnx", timeout=10) as res:
        assert res.headers["Content-Type"] == "application/octet-stream"
        assert res.read() == b"fake-onnx"


@pytest.mark.parametrize(
    "path", ["/photos/secret.jpg", "/notes.txt", "/../server.py", "/tests/", "/models/other.onnx"]
)
def test_other_paths_are_not_found(url: str, path: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(url + path, timeout=10)
    assert e.value.code == 404


def test_listens_only_on_this_computer(site: Path) -> None:
    server = make_server(FakeModel(SHOT), site, port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_model_not_exported_yet_is_not_found(site: Path) -> None:
    (site / "models" / "moge-2-s-fp16.onnx").unlink()
    for url in _serve(FakeModel(SHOT), site):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(url + "/models/moge-2-s-fp16.onnx", timeout=10)
    assert e.value.code == 404


def test_head_tells_the_model_size_without_sending_it(url: str) -> None:
    req = urllib.request.Request(url + "/models/moge-2-s-fp16.onnx", method="HEAD")
    with urllib.request.urlopen(req, timeout=10) as res:
        assert res.status == 200
        assert res.headers["Content-Length"] == str(len(b"\x08\x01fake-onnx"))
        assert res.read() == b""
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(
            urllib.request.Request(url + "/notes.txt", method="HEAD"), timeout=10
        )
    assert e.value.code == 404


def test_head_for_a_missing_file_has_no_body(url: str) -> None:
    # 用原始連線讀：urllib 遇到 HEAD 會自己丟掉內容，看不出伺服器有沒有多送
    crlf = bytes((13, 10))
    host, port = url.removeprefix("http://").split(":")
    with socket.create_connection((host, int(port)), timeout=10) as conn:
        conn.sendall(b"HEAD /notes.txt HTTP/1.0" + crlf * 2)
        raw = b""
        while chunk := conn.recv(4096):
            raw += chunk
    head, _, body = raw.partition(crlf * 2)
    assert head.startswith(b"HTTP/1.0 404")
    assert body == b""
