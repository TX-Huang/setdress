"""AI 生的形狀整理（shape.py）、存 GLB（glb.py）。驗收句子在 docs/model3d.md 第 3 到 5 句。"""

import json
import struct

import numpy as np
import pytest

import glb
import shape


def box(x0, y0, z0, x1, y1, z1):
    """一個方塊的點和面（12 個三角形，法線朝外）。"""
    v = np.array(
        [[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], dtype=np.float32
    )
    f = np.array(
        [
            [0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5],  # x0、x1
            [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],  # y0、y1
            [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3],  # z0、z1
        ],
        dtype=np.int64,
    )  # fmt: skip
    return v, f


def ell():
    """L 形（從 +Z 看）：一根直的（左邊、高）加一根橫的（底下、往右）。左右、上下都不對稱。"""
    v1, f1 = box(-1.0, -1.0, -0.2, -0.5, 1.0, 0.2)
    v2, f2 = box(-0.5, -1.0, -0.2, 1.0, -0.4, 0.2)
    return np.vstack([v1, v2]), np.vstack([f1, f2 + len(v1)])


def ell_photo(size=100):
    """L 形的去背照片（從 +Z 看，照片上面是 +Y）。

    商品範圍 [10, 10, 90, 90]，x、y 都是 1 單位 = 40 px。
    """
    alpha = np.zeros((size, size), dtype=np.uint8)
    alpha[10:90, 10:30] = 255  # 直的：x -1..-0.5 → 10..30，y 1..-1 → 10..90
    alpha[66:90, 30:90] = 255  # 橫的：x -0.5..1 → 30..90，y -0.4..-1 → 66..90
    return alpha


ROTATIONS = {
    "朝 -Z（看到背面）": np.diag([-1.0, 1.0, -1.0]),
    "朝 +X": np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], dtype=float),
    "躺下（上面朝 +Z）": np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float),
}


class TestRotations:
    def test_24_turns_no_mirrors_and_no_turn_first(self):
        rs = shape.rotations()
        assert len(rs) == 24
        assert all(np.isclose(np.linalg.det(r), 1) for r in rs), "不能鏡射（左右會反過來）"
        np.testing.assert_allclose(rs[0], np.eye(3))


class TestSilhouette:
    def test_a_2_by_1_box_fills_exactly_half_the_rows(self):
        v, f = box(-1.0, -0.5, -0.4, 1.0, 0.5, 0.4)
        s = shape.silhouette(v, f)
        assert s.any(axis=1).sum() == 32 and s.any(axis=0).sum() == 64


class TestOrient:
    def test_a_symmetric_shape_already_facing_the_camera_is_not_turned(self):
        """前後一樣的方塊：從 +Z、-Z 看都一樣像，選不轉的（不然照片會貼到背面）。"""
        v, f = box(-1.0, -0.5, -0.4, 1.0, 0.5, 0.4)
        alpha = np.zeros((60, 80), dtype=np.uint8)
        alpha[20:40, 20:60] = 255
        out, _ = shape.orient(v, f, alpha)
        np.testing.assert_allclose(out, v)

    @pytest.mark.parametrize("name", list(ROTATIONS))
    def test_turns_the_photo_side_to_face_the_camera_and_up_to_plus_y(self, name):
        v, f = ell()
        turned = v @ ROTATIONS[name].T
        out, score = shape.orient(turned, f, ell_photo())
        assert score > 0.9, f"{name}：輪廓重疊只有 {score:.2f}"
        np.testing.assert_allclose(shape.silhouette(out, f, 64), shape.silhouette(v, f, 64))

    def test_already_facing_the_camera_stays(self):
        v, f = ell()
        out, score = shape.orient(v, f, ell_photo())
        np.testing.assert_allclose(out, v, atol=1e-6)
        assert score > 0.9


class TestPick:
    def test_keeps_the_ai_s_own_direction_unless_another_is_clearly_better(self):
        """TripoSG 生的形狀本來就是照片那一面朝 +Z。

        前後對稱的椅子差一點點時不要轉（Codex 審查）。
        """
        assert shape.pick([0.80, 0.83, 0.5]) == 0
        assert shape.pick([0.60, 0.90, 0.5]) == 1


class TestPlace:
    def test_bottom_on_the_floor_and_centred(self):
        v, _ = box(1.0, 2.0, -3.0, 3.0, 5.0, -1.0)
        out = shape.place(v)
        np.testing.assert_allclose(out.min(axis=0), [-1.0, 0.0, -1.0])
        np.testing.assert_allclose(out.max(axis=0), [1.0, 3.0, 1.0])


class TestUv:
    def test_front_view_corners_land_on_the_photos_product_box(self):
        v, _ = box(-1.0, 0.0, -0.5, 1.0, 2.0, 0.5)
        uv = shape.photo_uv(v, box_px=[20, 10, 80, 90], photo_wh=(100, 200))
        left_top = np.flatnonzero((v[:, 0] == -1) & (v[:, 1] == 2))
        right_bottom = np.flatnonzero((v[:, 0] == 1) & (v[:, 1] == 0))
        np.testing.assert_allclose(uv[left_top], [[0.2, 0.05]] * len(left_top))
        np.testing.assert_allclose(uv[right_bottom], [[0.8, 0.45]] * len(right_bottom))

    def test_the_back_takes_the_same_place_in_the_photo_as_the_front(self):
        v, _ = box(-1.0, 0.0, -0.5, 1.0, 2.0, 0.5)
        uv = shape.photo_uv(v, box_px=[0, 0, 100, 100], photo_wh=(100, 100))
        front = (v[:, 2] == 0.5) & (v[:, 0] == -1) & (v[:, 1] == 0)
        back = (v[:, 2] == -0.5) & (v[:, 0] == -1) & (v[:, 1] == 0)
        np.testing.assert_allclose(uv[front], uv[back])


class TestModelInput:
    def test_product_on_white_cut_to_a_square_with_a_tenth_around(self):
        rgb = np.zeros((100, 200, 3), dtype=np.uint8)
        rgb[:] = (10, 200, 30)
        alpha = np.zeros((100, 200), dtype=np.uint8)
        alpha[20:60, 50:150] = 255  # 100 寬 x 40 高
        out = shape.model_input(rgb, alpha)
        assert out.shape == (120, 120, 3), "長邊 100 + 兩邊各一成"
        assert tuple(out[0, 0]) == (255, 255, 255)
        assert tuple(out[60, 60]) == (10, 200, 30)
        assert tuple(out[38, 60]) == (255, 255, 255), "商品上面是白的"
        assert tuple(out[40, 60]) == (10, 200, 30), "商品從 (120-40)/2 = 40 開始"


class TestGlb:
    def read(self, data):
        magic, version, length = struct.unpack_from("<4sII", data, 0)
        assert (magic, version, length) == (b"glTF", 2, len(data))
        json_len, json_type = struct.unpack_from("<I4s", data, 12)
        assert json_type == b"JSON"
        doc = json.loads(data[20 : 20 + json_len])
        bin_len, bin_type = struct.unpack_from("<I4s", data, 20 + json_len)
        assert bin_type == b"BIN\x00"
        return doc, data[28 + json_len : 28 + json_len + bin_len]

    def test_points_faces_and_photo_coordinates_no_picture(self):
        v, f = box(-1, 0, -1, 1, 2, 1)
        uv = np.zeros((len(v), 2), dtype=np.float32)
        doc, binary = self.read(glb.encode(v, f, uv))
        (prim,) = doc["meshes"][0]["primitives"]
        assert set(prim["attributes"]) == {"POSITION", "TEXCOORD_0"}
        pos = doc["accessors"][prim["attributes"]["POSITION"]]
        assert (pos["count"], pos["min"], pos["max"]) == (8, [-1, 0, -1], [1, 2, 1])
        idx = doc["accessors"][prim["indices"]]
        assert idx["count"] == 36 and idx["componentType"] == 5123, "點少於 65536 用 16 位元"
        assert "images" not in doc and "textures" not in doc, "沒有照片"
        assert len(binary) % 4 == 0

    def test_chunks_are_padded_to_4_bytes_even_with_an_odd_number_of_indices(self):
        v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        data = glb.encode(v, np.array([[0, 1, 2]]), np.zeros((3, 2), dtype=np.float32))
        json_len = struct.unpack_from("<I", data, 12)[0]
        assert len(data) % 4 == 0 and json_len % 4 == 0
        self.read(data)

    def test_many_points_use_32_bit_indices(self):
        n = 70000
        v = np.zeros((n, 3), dtype=np.float32)
        v[:, 0] = np.arange(n)
        f = np.array([[0, 1, n - 1]])
        doc, _ = self.read(glb.encode(v, f, np.zeros((n, 2), dtype=np.float32)))
        assert (
            doc["accessors"][doc["meshes"][0]["primitives"][0]["indices"]]["componentType"] == 5125
        )

    def test_same_input_same_bytes(self):
        v, f = box(-1, 0, -1, 1, 2, 1)
        uv = np.zeros((len(v), 2), dtype=np.float32)
        assert glb.encode(v, f, uv) == glb.encode(v.copy(), f.copy(), uv.copy())
