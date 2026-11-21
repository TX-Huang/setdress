"""存成 GLB（glTF 2.0 的二進位檔）：只有點、面、照片座標，沒有圖片（docs/model3d.md 第 3 句）。

照片是打開網頁時從店家讀來貼的，所以檔案裡不放。不用額外的套件。
"""

from __future__ import annotations

import json
import struct

import numpy as np

FLOAT, U16, U32 = 5126, 5123, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963


def _pad(data: bytes, fill: bytes) -> bytes:
    return data + fill * (-len(data) % 4)


def _view(offset: int, length: int, target: int) -> dict:
    return {"buffer": 0, "byteOffset": offset, "byteLength": length, "target": target}


def _accessor(view: int, kind: int, count: int, shape: str) -> dict:
    return {"bufferView": view, "componentType": kind, "count": count, "type": shape}


def encode(vertices: np.ndarray, faces: np.ndarray, uv: np.ndarray) -> bytes:
    """點（n, 3）、面（m, 3）、照片座標（n, 2）→ GLB 的 bytes。點少於 65536 個時面用 16 位元。"""
    pos = np.ascontiguousarray(vertices, dtype="<f4")
    tex = np.ascontiguousarray(uv, dtype="<f4")
    small = len(pos) < 65536
    idx = np.ascontiguousarray(faces, dtype="<u2" if small else "<u4").reshape(-1)
    blobs = [pos.tobytes(), tex.tobytes(), _pad(idx.tobytes(), b"\x00")]
    offsets = np.cumsum([0] + [len(b) for b in blobs[:-1]]).tolist()
    views = [
        _view(offsets[0], len(blobs[0]), ARRAY_BUFFER),
        _view(offsets[1], len(blobs[1]), ARRAY_BUFFER),
        _view(offsets[2], idx.nbytes, ELEMENT_ARRAY_BUFFER),
    ]
    position = _accessor(0, FLOAT, len(pos), "VEC3")
    position.update(min=pos.min(axis=0).tolist(), max=pos.max(axis=0).tolist())  # glTF 規定要有
    accessors = [
        position,
        _accessor(1, FLOAT, len(tex), "VEC2"),
        _accessor(2, U16 if small else U32, len(idx), "SCALAR"),
    ]
    binary = b"".join(blobs)
    primitive = {"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "indices": 2, "material": 0}
    doc = {
        "asset": {"version": "2.0", "generator": "setdress tools/model3d"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [primitive]}],
        "materials": [{"pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.9}}],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(binary)}],
    }
    text = _pad(json.dumps(doc, separators=(",", ":")).encode(), b" ")
    body = (
        struct.pack("<I4s", len(text), b"JSON")
        + text
        + struct.pack("<I4s", len(binary), b"BIN\x00")
        + binary
    )
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body
