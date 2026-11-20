"""從商品照片描側面輪廓（outline.py）。

測試用畫出來的形狀：答案是已知的，才知道描得準不準。
"""

import numpy as np
import pytest

import outline as ol

W, H = 200, 240


def draw(radius_at, *, bg=(255, 255, 255), fg=(40, 40, 40), cx=100, top=20, bottom=220, cord=False):
    """畫一個旋轉體的側面：每一列 |x - cx| <= radius_at(從底部算的高度)。"""
    img = np.zeros((H, W, 3), dtype=np.uint8)
    img[:] = bg
    for row in range(top, bottom + 1):
        r = radius_at(bottom - row)
        if r > 0:
            img[row, max(0, round(cx - r)) : round(cx + r) + 1] = fg
    if cord:  # 吊燈的電線：細細一條往上到照片頂端
        img[0:top, cx - 1 : cx + 2] = fg
    return img


def cone(h):  # 尖端朝上的圓錐：底部半徑 60，高 200
    return 60 * (1 - h / 200)


class TestForeground:
    def test_separates_the_object_from_a_white_background(self):
        mask = ol.foreground(draw(cone))
        assert mask[120, 100] and not mask[5, 5]

    def test_works_on_a_grey_background(self):
        mask = ol.foreground(draw(cone, bg=(225, 225, 225), fg=(250, 250, 250)))
        assert mask[150, 100] and not mask[5, 5]

    def test_a_white_object_with_a_thin_grey_edge_on_white_is_kept_whole(self):
        # 白色燈罩拍在白底上：只有邊緣一圈淡灰。被邊緣圍住的白色是燈罩，不是背景
        img = np.full((H, W, 3), 255, dtype=np.uint8)
        yy, xx = np.mgrid[:H, :W]
        d = np.hypot(yy - 120, xx - 100)
        img[(d > 58) & (d <= 61)] = (200, 200, 200)
        mask = ol.foreground(img)
        assert mask[120, 100], "圓圈裡面的白色要算燈"
        assert mask.sum() == pytest.approx(np.pi * 61**2, rel=0.05)

    def test_a_background_of_two_colours(self):
        # 上半白牆、下半灰地板：邊框的中位數不是任何一個顏色，以前會整張變成商品
        img = draw(cone)
        img[120:][np.all(img[120:] == 255, axis=2)] = (190, 190, 190)
        mask = ol.foreground(img)
        assert mask[150, 100] and not mask[5, 5] and not mask[230, 5]

    def test_grey_and_transparent_images(self):
        grey = draw(cone)[..., 0]
        assert ol.foreground(grey)[120, 100]
        rgba = np.dstack([draw(cone), np.full((H, W), 255, np.uint8)])
        rgba[:, :, 3][np.all(rgba[..., :3] == 255, axis=2)] = 0
        rgba[:, :, :3][rgba[:, :, 3] == 0] = (10, 10, 10)  # 透明的地方底下藏著黑色
        mask = ol.foreground(rgba)
        assert mask[120, 100] and not mask[5, 5]

    def test_an_empty_photo_says_so_instead_of_crashing(self):
        with pytest.raises(ol.NoProductError):
            ol.profile(ol.foreground(np.full((H, W, 3), 255, np.uint8)))

    def test_only_the_biggest_piece_is_kept(self):
        # 商品照常有角落的貼紙（「150th anniversary」圓章）
        img = draw(cone)
        img[5:25, 5:25] = (230, 120, 140)
        mask = ol.foreground(img)
        assert not mask[15, 15]


class TestProfile:
    def test_recovers_the_half_width_at_each_height(self):
        prof = ol.profile(ol.foreground(draw(cone)))
        got = dict(prof)
        for h in (0, 50, 100, 150):
            assert abs(got[h] - cone(h)) <= 1.5

    def test_heights_start_at_the_lowest_point(self):
        prof = ol.profile(ol.foreground(draw(cone)))
        assert min(h for h, _ in prof) == 0
        assert max(h for h, _ in prof) == pytest.approx(200, abs=1)

    def test_a_pendant_cord_on_top_is_cut_off(self):
        # 吊燈罩：高 120，頂端還有 30 寬，電線接得上（Codex 審查：以前的電線沒接上燈罩）
        def dome(h):
            return 80 * np.sqrt(max(0.0, 1 - (h / 130) ** 2))

        mask = ol.foreground(draw(dome, top=100, bottom=220, cord=True))
        assert mask[50, 100], "電線跟燈罩連在一起，剪電線的是 profile，不是「只留最大一塊」"
        top = max(h for h, _ in ol.profile(mask))
        assert top == pytest.approx(120, abs=2), "電線不是燈罩的高度"

    def test_a_thin_top_that_widens_is_not_a_cord(self):
        # 照片頂端切到的尖頂：細，但越往下越寬 —— 電線是一樣細的
        def spire(h):  # 頂端只剩 1.5 寬、一路變寬的尖頂，頂到照片最上面
            return 60 * (1 - h / 205)

        prof = ol.profile(ol.foreground(draw(spire, top=0, bottom=200)))
        assert max(h for h, _ in prof) == pytest.approx(200, abs=2)

    def test_a_long_shadow_on_one_side_does_not_move_the_centre(self):
        img = draw(cone)
        img[90:221, 100:195] = np.where(img[90:221, 100:195] == 255, 205, img[90:221, 100:195])
        prof = dict(ol.profile(ol.foreground(img)))
        assert abs(prof[5] - cone(5)) <= 2

    def test_a_shadow_on_one_side_does_not_widen_the_base(self):
        # 商品照常有落在一邊的影子（JWDA、Carrie）：底座會被量寬，整盞燈的比例就歪了
        img = draw(cone)
        img[205:221, 100:190] = (200, 200, 200)  # 底部右邊一片淡灰影子
        prof = dict(ol.profile(ol.foreground(img)))
        assert abs(prof[5] - cone(5)) <= 1.5

    def test_an_off_centre_object_still_finds_its_own_axis(self):
        prof = ol.profile(ol.foreground(draw(cone, cx=70)))
        assert abs(dict(prof)[0] - 60) <= 1.5


class TestPhotoProblem:
    """批次用：照片能不能拿來描。要單色背景的側面、轉一圈的形狀（docs/outline.md 第 8、9 句）。"""

    def test_a_clean_side_view_is_fine(self):
        assert ol.photo_problem(ol.foreground(draw(cone))) is None

    def test_a_pendant_cord_touching_the_top_is_fine(self):
        assert ol.photo_problem(ol.foreground(draw(cone, cord=True))) is None

    def test_touching_the_bottom_is_fine(self):
        # 立燈拍到照片底部。底座只佔邊框一小段（寬到佔一成以上，那個顏色就會被當成背景色）
        assert ol.photo_problem(ol.foreground(draw(lambda h: 25, bottom=H - 1))) is None

    def test_touching_the_left_edge_means_the_photo_is_cut_or_not_plain(self):
        assert ol.photo_problem(ol.foreground(draw(cone, cx=40))) == ol.CUT_OFF

    def test_touching_the_right_edge_too(self):
        assert ol.photo_problem(ol.foreground(draw(cone, cx=W - 40))) == ol.CUT_OFF

    def test_an_arm_sticking_out_on_one_side_is_lopsided(self):
        # 細桿（半徑 15）的上面三成，右邊伸出一支手臂：不是轉一圈的形狀
        img = draw(lambda h: 15)
        img[20:80, 100:180] = (40, 40, 40)
        assert ol.photo_problem(ol.foreground(img)) == ol.LOPSIDED

    def test_a_short_arm_on_a_seventh_of_the_height_is_still_caught(self):
        img = draw(lambda h: 15)
        img[60:90, 100:180] = (40, 40, 40)  # 30 列，佔 201 列的 15%
        assert ol.photo_problem(ol.foreground(img)) == ol.LOPSIDED

    def test_a_shadow_on_one_side_of_the_bottom_tenth_is_not_lopsided(self):
        img = draw(cone)
        # 底下一成（201 列的最後 21 列）右邊一片影子。這一成如果也算，第 90 百分位就會落在影子上
        img[200:221, 100:190] = (200, 200, 200)
        assert ol.photo_problem(ol.foreground(img)) is None


class TestScale:
    def test_scales_by_the_real_width(self):
        prof = [(0, 50.0), (100, 25.0), (200, 0.0)]  # (高 px, 半寬 px)
        pts, height_cm = ol.to_cm(prof, width_cm=40)
        assert height_cm == pytest.approx(80)
        assert pts[0] == pytest.approx((20.0, 0.0))

    def test_with_both_real_width_and_height_each_axis_is_scaled_on_its_own(self):
        prof = [(0, 50.0), (100, 25.0), (200, 0.0)]
        pts, measured = ol.to_cm(prof, width_cm=40, height_cm=100)
        assert measured == pytest.approx(80), "量出來的高度照樣回報，拿來檢查照片角度"
        assert max(h for _, h in pts) == pytest.approx(100)
        assert max(r for r, _ in pts) == pytest.approx(20)

    def test_zero_width_is_an_error_not_a_crash(self):
        with pytest.raises(ol.NoProductError):
            ol.to_cm([(0, 0.0), (10, 0.0)], width_cm=40)

    def test_simplify_keeps_the_shape_with_fewer_points(self):
        pts = [(cone(h) / 10, h / 10) for h in range(0, 201)]
        simple = ol.simplify(pts, tol=0.1)
        assert len(simple) <= 4
        assert simple[0] == pts[0] and simple[-1] == pts[-1]


class TestCompare:
    def test_same_shape_overlaps_fully(self):
        a = [(5.0, 0.0), (5.0, 10.0)]
        assert ol.overlap(a, a) == pytest.approx(1.0)

    def test_half_as_wide_overlaps_half(self):
        a, b = [(10.0, 0.0), (10.0, 10.0)], [(5.0, 0.0), (5.0, 10.0)]
        assert ol.overlap(a, b) == pytest.approx(0.5, abs=0.02)

    def test_hand_made_parts_become_a_profile(self):
        # 原型 lamps.js 的零件：旋轉體、圓柱、球（只算跟中心軸同一條線的）
        parts = [
            {"k": "cyl", "r": 2, "h": 10, "at": [0, 5, 0]},
            {"k": "sphere", "r": 6, "at": [0, 16, 0]},
            {"k": "cyl", "r": 9, "h": 1, "at": [30, 5, 0]},  # 偏離中心軸（壁燈的支架）不算
        ]
        prof = dict((round(h), round(r, 1)) for r, h in ol.parts_profile(parts, step=1.0))
        assert prof[3] == 2
        assert prof[16] == 6

    def test_parts_keep_their_taper_squash_offset_and_rims(self):
        parts = [
            {"k": "cyl", "r": 2, "r2": 6, "h": 10, "at": [0, 5, 0]},  # r 是上半徑、r2 是下半徑
            {"k": "sphere", "r": 4, "sy": 0.5, "at": [0, 12, 0]},  # 壓扁：上下只有 2
            {"k": "lathe", "pts": [[1, 0], [9, 0]], "at": [0, 20, 0]},  # 平的邊（帽沿）
        ]
        prof = dict((round(h, 1), round(r, 2)) for r, h in ol.parts_profile(parts, step=0.5))
        assert prof[0.0] == 6 and prof[10.0] == pytest.approx(2, abs=0.05)
        assert prof[12.0] == 4
        assert 14.5 not in prof or prof[14.5] == 0
        assert prof[20.0] == 9, "平的邊取外面那圈"

    def test_a_thin_part_between_samples_is_not_lost(self):
        parts = [
            {"k": "cyl", "r": 2, "h": 10, "at": [0, 5, 0]},
            {"k": "cyl", "r": 8, "h": 0.2, "at": [0, 2.2, 0]},
        ]  # 2.1 到 2.3 cm 的薄凸緣
        assert max(r for r, _ in ol.parts_profile(parts, step=0.5)) == 8

    def test_a_lamp_with_nothing_on_the_axis_has_no_profile(self):
        # 壁燈：零件都偏到牆邊或橫著放，沒有「轉一圈」的形狀可以比
        parts = [
            {"k": "cyl", "r": 5, "h": 10, "at": [0, 5, 3], "axis": "z"},
            {"k": "box", "s": [5, 5, 5]},
        ]
        assert ol.parts_profile(parts) == []
