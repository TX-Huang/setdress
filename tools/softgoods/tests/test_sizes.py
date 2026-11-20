"""從介紹文字找「尺寸那一行」（規格：SIZES.md）。

案例取自 2026-11-20 抓到的 4 家 Shopify 店。只留尺寸那幾行和必要的上下文，
介紹文字本身有著作權，不放進來。
"""

import pytest

from softgoods import normalize as nz
from softgoods import sizes


def html(*lines: str) -> str:
    return "".join(f"<p>{ln}</p>" for ln in lines)


class TestTextLines:
    def test_tags_become_line_breaks(self):
        body = "<p>第一行</p><p>尺寸<br>寬 20 x 高 35.5 cm</p><ul><li>重量 1 kg</li></ul>"
        assert sizes.text_lines(body) == ["第一行", "尺寸", "寬 20 x 高 35.5 cm", "重量 1 kg"]

    def test_a_table_row_stays_on_one_line(self):
        # NOSA 的「產品尺寸」是表格：一格寫「寬」、下一格寫「25 cm」
        body = "<table><tr><td>寬</td><td>25 cm</td></tr><tr><td>深</td><td>43.5 cm</td></tr></table>"
        assert sizes.text_lines(body) == ["寬 25 cm", "深 43.5 cm"]

    def test_newlines_inside_the_html_source_are_just_spaces(self):
        # 真實的 NOSA 原始碼：格子之間有換行。HTML 裡換行只是空白，不是分行
        body = """<table>
<tr>
<td>長</td>
<td>182 cm</td>
</tr>
<tr>
<td>寬</td>
<td>50
cm</td>
</tr>
</table>"""
        assert sizes.text_lines(body) == ["長 182 cm", "寬 50 cm"]

    def test_html_entities_are_decoded(self):
        assert sizes.text_lines("<p>寬&nbsp;20&nbsp;cm &amp; 高 30 cm</p>") == ["寬 20 cm & 高 30 cm"]

    @pytest.mark.parametrize("body", [None, "", "<p></p>"])
    def test_empty(self, body):
        assert sizes.text_lines(body) == []


class TestSizeSnippet:
    def test_a_labelled_line(self):
        body = html("一段介紹。", "尺寸：寬 19 x 深 28 x 高 28 cm，充電線長 200 cm", "材質：ABS")
        assert sizes.size_snippet(body) == "寬 19 x 深 28 x 高 28 cm，充電線長 200 cm"

    def test_lines_under_a_heading_are_joined(self):
        # 居雅堂：標題「尺寸」單獨一行，下面幾行才是數字
        body = html(
            "介紹。",
            "尺寸",
            "寬 × 高 × 深：285 × 307 × 285 mm",
            "燈罩直徑：Ø285 mm",
            "光源高度可調：約 40 mm（依所選燈泡而定）",
        )
        assert sizes.size_snippet(body) == "寬 × 高 × 深：285 × 307 × 285 mm，燈罩直徑：Ø285 mm"

    @pytest.mark.parametrize("heading", ["產品尺寸", "尺寸 SIZE", "Dimensions"])
    def test_heading_variants(self, heading):
        assert sizes.size_snippet(html(heading, "W250 × D250 × H122 mm")) == "W250 × D250 × H122 mm"

    def test_a_size_table_under_a_heading(self):
        body = (
            "<h3>產品尺寸</h3><table><tr><td>寬</td><td>25 cm</td></tr>"
            "<tr><td>深</td><td>43.5 cm</td></tr><tr><td>高</td><td>112.5 cm</td></tr></table>"
        )
        assert sizes.size_snippet(body) == "寬 25 cm，深 43.5 cm，高 112.5 cm"

    def test_a_note_in_brackets_does_not_throw_the_line_away(self):
        # 「（燈臂可調）」有「可調」，但它只是註記，尺寸本身是好的
        body = html("產品尺寸", "寬 180 × 深 65 × 高 200 cm（燈臂可調）")
        assert sizes.size_snippet(body) == "寬 180 × 深 65 × 高 200 cm"

    def test_falls_back_to_a_segment_with_labelled_sizes(self):
        # NOSA：沒有「尺寸」兩個字，尺寸跟材質用｜串在一行
        body = html("介紹。", "寬12 cm × 深65 cm × 高65 cm｜材質：Oak wood｜顏色：米色")
        assert sizes.size_snippet(body) == "寬12 cm × 深65 cm × 高65 cm"

    def test_a_line_with_two_things_reads_the_main_size(self):
        # 吸頂蓋的 11 cm 是配件，不能變成燈的尺寸
        body = html("尺寸: 燈體：30 × 30 × 10 cm / 吸頂蓋（Ceiling Cover）：11 cm")
        got = nz.parse_dimensions(sizes.size_snippet(body))
        assert got == {"width_mm": 300, "depth_mm": 300, "height_mm": 100}

    @pytest.mark.parametrize(
        "line",
        [
            "電線：織布電線 2 x 0.75 mm²，附插頭，長度 3 公尺",
            "燈桿高度可於 148 至 175 公分之間調整",
            "燈罩可延伸 Ø40 ~ Ø70 cm",
        ],
    )
    def test_things_that_are_not_the_product_size(self, line):
        assert sizes.size_snippet(html("介紹。", line)) is None

    def test_prose_without_labels_is_not_trusted(self):
        # 「21 cm 見方、32 cm 高」是句子，沒有標籤格式，寧可不猜
        assert sizes.size_snippet(html("Ovo 是 21 cm 見方、32 cm 高的鐵件檯燈。")) is None

    def test_very_long_lines_are_prose_not_sizes(self):
        long_line = "尺寸：" + "這是一段很長的介紹文字，" * 12 + "寬 20 cm"
        assert sizes.size_snippet(html(long_line)) is None

    @pytest.mark.parametrize("body", [None, "", html("只有介紹，沒有數字。")])
    def test_nothing_found_returns_none(self, body):
        assert sizes.size_snippet(body) is None


class TestPerVariant:
    BODY = html("AKARI 3X (W240 × H370 mm)", "AKARI 4N (W220 × H520 mm)", "燈泡規格：E27 40W")

    @pytest.mark.parametrize(
        "variant, want",
        [
            ("現貨 / 3X", "AKARI 3X (W240 × H370 mm)"),
            ("預購 / 4N", "AKARI 4N (W220 × H520 mm)"),
        ],
    )
    def test_picks_the_line_that_names_the_variant(self, variant, want):
        assert sizes.size_snippet(self.BODY, variant) == want

    def test_no_match_takes_the_first(self):
        assert sizes.size_snippet(self.BODY, "白色") == "AKARI 3X (W240 × H370 mm)"

    def test_variant_words_match_whole_words_only(self):
        # 規格名「N」不能從「4N」裡配到；一個字母的規格名不配對（SIZES.md「不做的」）
        assert sizes.size_snippet(self.BODY, "N") == "AKARI 3X (W240 × H370 mm)"


class TestProductPages:
    """潤舍的尺寸只在商品頁（SIZES.md「潤舍是特例」）。整頁 0.7 MB，存快取前先瘦身。"""

    PAGE = (
        '<html><head><style>.a{color:red}</style><script>var d = "尺寸：寬 99 cm";</script></head>'
        '<body><div class="product-text"><p><strong>商品資訊</strong></p>'
        '<div class="metafield-rich_text_field"><p>尺寸：寬 19 x 深 28 x 高 28 cm</p></div>'
        "<p>光源：LED</p></div><!-- 註解 --><svg><path d='M0 0'/></svg></body></html>"
    )

    def test_scripts_and_styles_are_not_read(self):
        assert sizes.size_snippet(self.PAGE) == "寬 19 x 深 28 x 高 28 cm"

    def test_slim_html_drops_scripts_styles_svg_comments_and_attributes(self):
        slim = sizes.slim_html(self.PAGE)
        for gone in ("<script", "<style", "<svg", "<!--", "class=", "寬 99"):
            assert gone not in slim
        assert len(slim) < len(self.PAGE)

    def test_slim_html_keeps_what_the_size_finder_needs(self):
        assert sizes.size_snippet(sizes.slim_html(self.PAGE)) == sizes.size_snippet(self.PAGE)


class TestReviewFixes:
    """Codex 審查（2026-11-20）抓到的情況。"""

    def test_prose_after_the_size_is_cut_off(self):
        body = html("尺寸：寬 30 cm，採用手工編織純棉布料與獨家圖案。")
        assert sizes.size_snippet(body) == "寬 30 cm"

    def test_a_wattage_after_the_size_does_not_throw_the_size_away(self):
        assert sizes.size_snippet(html("尺寸：寬 20 × 高 30 cm，光源 40W")) == "寬 20 × 高 30 cm"

    def test_a_note_after_the_size_without_brackets(self):
        assert sizes.size_snippet(html("尺寸：寬 20 × 高 30 cm 燈臂可調")) == "寬 20 × 高 30 cm"

    @pytest.mark.parametrize("line", ["尺寸：寬 30-50 cm", "尺寸：寬 30–50 cm", "尺寸：高 148 到 175 cm"])
    def test_a_range_is_not_a_size(self, line):
        assert sizes.size_snippet(html(line)) is None

    def test_a_wire_spec_stays_out_even_when_a_length_follows(self):
        assert sizes.size_snippet(html("尺寸：電線 2 x 0.75 mm²，長度 3 公尺")) is None

    def test_variant_rows_under_one_heading_stay_apart(self):
        body = html("尺寸", "AKARI 3X (W240 × H370 mm)", "AKARI 4N (W220 × H520 mm)")
        assert sizes.size_snippet(body, "預購 / 4N") == "AKARI 4N (W220 × H520 mm)"
        assert sizes.size_snippet(body, "現貨 / 3X") == "AKARI 3X (W240 × H370 mm)"


class TestTitleHint:
    """潤舍：Lantern 小、中、大三頁的介紹文字一模一樣，都列了三種尺寸；哪一頁是哪個尺寸，寫在標題裡。"""

    BODY = html(
        "尺寸",
        "小尺寸：圓直徑 20 x 高 22 cm",
        "中尺寸：圓直徑 30 x 高 32 cm",
        "大尺寸：圓直徑 40 x 高 42 cm",
    )

    def test_the_size_in_the_title_picks_the_line(self):
        got = sizes.size_snippet(self.BODY, "象牙白玻璃", title="New Works Lantern 桌燈 (Ø40 cm)")
        assert got == "大尺寸：圓直徑 40 x 高 42 cm"

    def test_a_variant_word_still_wins(self):
        got = sizes.size_snippet(self.BODY, "中尺寸", title="New Works Lantern 桌燈 (Ø40 cm)")
        assert got == "中尺寸：圓直徑 30 x 高 32 cm"

    def test_a_title_size_needs_a_label(self):
        # 「沙發套 305cm (… 305cm)」沒說是寬還是長，兩個 305 會被當成寬和深
        assert sizes.title_size("HKliving Nomad 沙發套 305cm (Nomad couch cover: 305cm)") is None
        assert sizes.title_size("Brokis Balloons 桌燈 (H40 cm)") == "Brokis Balloons 桌燈 (H40 cm)"

    def test_numbers_in_a_model_name_are_not_a_size_hint(self):
        # 「PH 3/2」不是尺寸（沒有單位），不能拿來挑
        assert sizes.size_snippet(self.BODY, "白色", title="PH 3/2 桌燈") == "小尺寸：圓直徑 20 x 高 22 cm"


class TestBlockTags:
    def test_a_new_block_starts_a_new_line(self):
        # Shopline：選單 </nav> 後面直接接介紹 <div>，沒有分行就會黏成「全部商品 燈具尺寸：…」
        body = "<nav>全部商品 燈具</nav><div class='d'><h3><span>尺寸：寬 20 cm</span></h3></div>"
        assert sizes.text_lines(body) == ["全部商品 燈具", "尺寸：寬 20 cm"]
