"""正規化層的測試。

這一層是整個專案最容易出錯的地方：30 個網站會用 30 種方式寫同一個尺寸。
所以測試案例全部取自真實抓到的字串，不是我自己編的。
"""

from typing import ClassVar

import pytest

from softgoods import normalize as nz

# ---------------------------------------------------------- 尺寸


class TestParseDimensions:
    """尺寸一律換成 mm 整數。原始字串由呼叫方另外留。"""

    @pytest.mark.parametrize(
        "raw, want",
        [
            # --- 真實案例（從 lampclub.tw 抓到的）
            ("Ø12.5 x 高 21 cm", {"diameter_mm": 125, "height_mm": 210}),
            ("圓直徑 12.5 x 高 21 cm", {"diameter_mm": 125, "height_mm": 210}),
            ("寬 19.1 x 高 10.8 x 深 15 cm", {"width_mm": 191, "height_mm": 108, "depth_mm": 150}),
            ("燈罩Ø 45 cm，高 25.2 cm", {"diameter_mm": 450, "height_mm": 252}),
            # --- 家具常見寫法
            ("W180×D90×H75cm", {"width_mm": 1800, "depth_mm": 900, "height_mm": 750}),
            ("W 180 x D 90 x H 75 cm", {"width_mm": 1800, "depth_mm": 900, "height_mm": 750}),
            # --- 地毯常用英制。攤平的東西沒有高度，所以是寬 x 深
            ("5 x 8 ft", {"width_mm": 1524, "depth_mm": 2438}),
            ("200 x 300 cm", {"width_mm": 2000, "depth_mm": 3000}),
            # --- 配件長度不是商品尺寸（跑真實資料踩到的坑）
            # 「電線長 200 cm」原本被當成寬度 2000mm
            ("桌燈 · Ø28 x 高 42.5 cm，電線長 200 cm", {"diameter_mm": 280, "height_mm": 425}),
            (
                "無線桌燈 · 寬 19 x 深 28 x 高 28 cm，充電線長 200 cm",
                {"width_mm": 190, "depth_mm": 280, "height_mm": 280},
            ),
            ("吊燈 · Ø45 cm，吊線長 150 cm", {"diameter_mm": 450}),
            ("鍊長 120 cm", {}),  # 只有配件長度 → 沒有商品尺寸可報
            # --- 其他單位
            ("直徑 40 公分", {"diameter_mm": 400}),
            ("高 1.8 m", {"height_mm": 1800}),
            ("寬 450 mm", {"width_mm": 450}),
            ('24" 寬', {"width_mm": 610}),
            # --- 全形數字和符號也要吃
            ("寬１８０ｘ高７５cm", {"width_mm": 1800, "height_mm": 750}),
        ],
    )
    def test_parses_real_world_strings(self, raw, want):
        assert nz.parse_dimensions(raw) == want

    @pytest.mark.parametrize("raw", ["", "   ", "全電壓", None, "依訂製", "尺寸請洽詢"])
    def test_no_numbers_gives_empty(self, raw):
        assert nz.parse_dimensions(raw) == {}

    def test_three_unlabelled_numbers_are_w_d_h(self):
        assert nz.parse_dimensions("180 x 90 x 75 cm") == {
            "width_mm": 1800,
            "depth_mm": 900,
            "height_mm": 750,
        }

    def test_cm_is_the_default_unit_when_none_given(self):
        # 軟裝業幾乎都講公分，沒寫單位就當 cm
        assert nz.parse_dimensions("寬 45 x 高 30") == {"width_mm": 450, "height_mm": 300}

    def test_rounds_to_whole_mm(self):
        assert nz.parse_dimensions("Ø12.55 cm") == {"diameter_mm": 126}


# ---------------------------------------------------------- 價格


class TestParsePrice:
    @pytest.mark.parametrize(
        "raw, want",
        [
            ("NT$7,600", 7600),
            ("NT$ 7,600 起", 7600),
            ("$1,234,567", 1234567),
            ("7600", 7600),
            ("60200.00", 60200),  # Shopify 給的是字串小數
            ("NT$0", 0),
            ("", None),
            (None, None),
            ("洽詢", None),
            ("價格請來電", None),
        ],
    )
    def test_price(self, raw, want):
        assert nz.parse_price(raw) == want

    def test_returns_int_not_float(self):
        # 錢不要用 float 算，會有誤差
        assert isinstance(nz.parse_price("60200.00"), int)


# ---------------------------------------------------------- 品牌


class TestBrandId:
    @pytest.mark.parametrize(
        "raw", ["Flos", "FLOS", "flos", "  Flos  ", "Flos Italia", "Flos Italy", "弗洛斯"]
    )
    def test_all_spellings_map_to_one_id(self, raw):
        aliases = {"flos": ["Flos", "FLOS", "Flos Italia", "Flos Italy", "弗洛斯"]}
        assert nz.brand_id(raw, aliases) == "flos"

    def test_unknown_brand_falls_back_to_slug(self):
        assert nz.brand_id("Santa & Cole", {}) == "santa-cole"
        assert nz.brand_id("Audo Copenhagen", {}) == "audo-copenhagen"

    def test_chinese_brand_keeps_characters(self):
        assert nz.brand_id("北歐櫥窗", {}) == "北歐櫥窗"

    def test_empty_is_unknown(self):
        assert nz.brand_id("", {}) == "unknown"
        assert nz.brand_id(None, {}) == "unknown"


# ---------------------------------------------------------- 分類


class TestMapCategory:
    MAPPING: ClassVar[dict] = {
        "吊燈": ("lighting", "pendant"),
        "pendant lamp": ("lighting", "pendant"),
        "桌燈": ("lighting", "table"),
        "單椅": ("furniture", "chair"),
        "accent chair": ("furniture", "chair"),
    }

    @pytest.mark.parametrize("raw", ["吊燈", "Pendant Lamp", "pendant lamp", "  吊燈  "])
    def test_same_thing_in_any_language_maps_the_same(self, raw):
        assert nz.map_category(raw, self.MAPPING) == ("lighting", "pendant")

    def test_slash_separated_types_try_each_part(self):
        # 真實資料：Shopify 店常把 product_type 寫成「擺飾 / 雕塑 / 壁飾」
        mapping = {"雕塑": ("decor", "sculpture")}
        assert nz.map_category("擺飾 / 雕塑 / 壁飾", mapping) == ("decor", "sculpture")

    def test_whole_string_beats_a_part(self):
        mapping = {"桌燈 / 檯燈": ("lighting", "table"), "檯燈": ("lighting", "floor")}
        assert nz.map_category("桌燈 / 檯燈", mapping) == ("lighting", "table")

    @pytest.mark.parametrize("sep", ["/", "、", ",", "|"])
    def test_common_separators(self, sep):
        mapping = {"雕塑": ("decor", "sculpture")}
        assert nz.map_category(f"擺飾{sep}雕塑", mapping) == ("decor", "sculpture")

    def test_unmapped_returns_none_so_you_can_find_the_gaps(self):
        # 回 None 而不是猜，這樣才查得出「還有哪些分類沒對應」
        assert nz.map_category("按摩椅", self.MAPPING) == (None, None)

    def test_empty_returns_none(self):
        assert nz.map_category("", self.MAPPING) == (None, None)


# ---------------------------------------------------------- 交期


class TestLeadTime:
    @pytest.mark.parametrize(
        "raw, want_days",
        [
            ("現貨", 0),
            ("可下單 4 - 6 個月", 120),  # 回最快的那個：4 個月
            ("預購 6 - 8 個月", 180),
            ("預計 3 週到貨", 21),
            ("約 10 天", 10),
            ("3-5 個工作日", 3),
            ("", None),
            (None, None),
            ("已完售", None),
        ],
    )
    def test_lead_time(self, raw, want_days):
        assert nz.parse_lead_time(raw) == want_days

    def test_returns_fastest_bound_because_stock_text_keeps_the_original(self):
        # 回「最快多久」。想看最慢的，去看 listing.stock_text 原文
        assert nz.parse_lead_time("4 - 6 個月") == 120


class TestPackSize:
    """多盞組的尺寸跟單盞一樣，不看組數就會把五盞組跟單盞放在一起比價。

    案例全部取自真實資料（Lee Broom Crescent 那一組）。
    """

    @pytest.mark.parametrize(
        "raw, want",
        [
            # 真的是組合
            ("MINI CRESCENT 三盞吊燈組", 3),
            ("英國LEE BROOM | Mini Crescent 五盞吊燈組", 5),
            ("2件組", 2),
            ("雙盞壁燈", 2),
            ("Set of 3", 3),
            ("Pendant 4 pcs", 4),
            ("12 入", 12),
            # 不是組合 —— 這幾個最容易誤判
            ("Artemide Tolomeo 三節閱讀立燈", 1),  # 三節燈臂，不是三盞
            ("Artemide Tolomeo 雙頭款吊燈", 1),  # 一盞兩頭
            ("Lee Broom Crescent 吊燈", 1),
            ("Louis Poulsen PH 3/3", 1),  # 型號裡的數字
            ("吊燈 · Ø20 x H22 cm", 1),  # 尺寸裡的數字
            ("", 1),
            (None, 1),
        ],
    )
    def test_pack_size(self, raw, want):
        assert nz.pack_size(raw) == want

    def test_single_item_is_one_not_zero_or_none(self):
        # 回 1 而不是 None，這樣比價的 group by 才不會把單品全併在一起
        assert nz.pack_size("Bell 無線桌燈") == 1


class TestInStock:
    @pytest.mark.parametrize(
        "raw, want", [("現貨", True), ("有現貨", True), ("可下單", False), ("預購 6-8 個月", False),
                      ("已完售", False), ("補貨中", False), ("", None), (None, None)]
    )
    def test_only_real_stock_counts_as_in_stock(self, raw, want):
        # 「可下單」不是現貨 —— 這個差別對買家最重要
        assert nz.in_stock(raw) is want


# ---------------------------------------------------------- 顏色


class TestCleanTitle:
    """從通路的商品標題挖出真正的型號。

    通路會在標題塞一堆東西：促銷詞、品牌名、分類詞、顏色。
    挖不出型號，就沒辦法比對「兩個站是不是同一款」。
    """

    @pytest.mark.parametrize(
        "title, brand, want_model, want_color",
        [
            # 真實標題（潤舍 Shopify）
            ("【 展示品出清 】Tom Dixon Puff 吊燈 (黃銅)", "Tom Dixon", "Puff", "黃銅"),
            ("Flos Bellhop V3 無線桌燈", "Flos", "Bellhop V3", None),
            ("Bell Portable 圓鐘 可攜式無線桌燈（紅銅）", "Tom Dixon", "Bell Portable 圓鐘", "紅銅"),
            # 分類詞只在結尾才拿掉 —— Tom Dixon 真的有一款叫 "Beat Light Fat"
            ("Tom Dixon Beat Light Fat 吊燈", "Tom Dixon", "Beat Light Fat", None),
            # 促銷雜訊
            ("【預購】Flos IC Lights T1 桌燈", "Flos", "IC Lights T1", None),
            ("[現貨] Flos Arco 立燈", "Flos", "Arco", None),
            # 品牌沒出現在標題裡也要正常
            ("Skye 吊燈", "Ferm Living", "Skye", None),
        ],
    )
    def test_extracts_model_and_colour(self, title, brand, want_model, want_color):
        assert nz.clean_title(title, brand) == (want_model, want_color)

    def test_does_not_strip_a_category_word_in_the_middle(self):
        model, _ = nz.clean_title("Tom Dixon Beat Light Fat 吊燈", "Tom Dixon")
        assert "Light" in model, "'Light' 是型號的一部分，不是分類詞"

    def test_never_returns_empty(self):
        # 整個標題都是分類詞的極端情況，寧可留原文也不要回空字串
        model, _ = nz.clean_title("吊燈", "Flos")
        assert model


class TestColorFamily:
    @pytest.mark.parametrize(
        "raw, want",
        [
            ("紅銅", "metallic"),
            ("黃銅", "metallic"),
            ("霧黑", "black"),
            ("消光黑", "black"),
            ("Matt Black", "black"),
            ("白", "white"),
            ("米白", "white"),
            ("橄欖綠", "green"),
            ("透明", "clear"),
            ("", None),
            ("特仕版", None),  # 不是顏色，不要猜
        ],
    )
    def test_color_family(self, raw, want):
        assert nz.color_family(raw) == want
