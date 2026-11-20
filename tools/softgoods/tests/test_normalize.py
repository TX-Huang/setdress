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
            # --- 標籤全寫在前面、數字全寫在後面（居雅堂 2026-11-20）。要照順序對：第二個是高
            (
                "寬 × 高 × 深：285 × 307 × 285 mm",
                {"width_mm": 285, "height_mm": 307, "depth_mm": 285},
            ),
            (
                "寬 × 高 × 出牆深度：200 × 236 × 323 mm",
                {"width_mm": 200, "height_mm": 236, "depth_mm": 323},
            ),
            ("W x D x H: 60 x 45 x 80 cm", {"width_mm": 600, "depth_mm": 450, "height_mm": 800}),
            # --- 電壓不是尺寸（潤舍的規格名、lampclub 的規格字串都有）
            ("透明玻璃｜黑色底座 (110-240V 適用)", {}),
            ("吊燈 · 110/220V", {}),
            ("110V (Ø40)", {"diameter_mm": 400}),
            ("煙燻灰 (LED 110V)", {}),
            ("白色大理石 (110-240V電壓適用)", {}),  # V 後面直接接中文
            ("暖光 3000K色溫", {}),
            ("230 / 3000k / DALI", {}),  # 小寫 k 也是色溫
            # --- 人工抽查 30 件找到的（2026-11-20）
            ("預購 / W1000 D600 H2080 / White 白", {"width_mm": 1000, "depth_mm": 600, "height_mm": 2080}),
            ("燈罩：∅ 50 x 高 10 cm，電線長度 300 cm", {"diameter_mm": 500, "height_mm": 100}),
            ("Type B 箱型×1＋分隔×2 / Texture White 霧面白", {}),
            ("W600 D400 H625 / Deep Yellow / 金屬鋼板x1、PC板x1", {"width_mm": 600, "depth_mm": 400, "height_mm": 625}),
            # --- 長和寬都寫了：長是寬（長邊），寬是深。不然深會不見（人工抽查 2026-11-20）
            ("長 × 寬 × 高：130 × 120 × 73 cm", {"width_mm": 1300, "depth_mm": 1200, "height_mm": 730}),
            ("寬 65 cm x 長 65 cm x 高 73 cm", {"width_mm": 650, "depth_mm": 650, "height_mm": 730}),
            ("長 182 cm，寬 50 cm，高 212 cm", {"width_mm": 1820, "depth_mm": 500, "height_mm": 2120}),
            # --- 單位後面不能接英文字母：「200 min」的 m 不是公尺
            ("寬 130 cm，總高度 200 min - 405 cm", {"width_mm": 1300, "height_mm": 2000}),
            # --- 沒寫單位（人工抽查 2026-11-20：5500 筆規格名沒有單位）
            # 數字大（≥ 400）當 mm：Sheeper 都寫 mm 不寫單位；4 m 以上的軟裝很少見
            ("W 1,200 × D 600 × H 320", {"width_mm": 1200, "depth_mm": 600, "height_mm": 320}),
            ("預購 / W730 x D300", {"width_mm": 730, "depth_mm": 300}),
            # 數字小當公分：床墊、地毯
            ("180x200 / Roller Slate / Oak", {"width_mm": 1800, "depth_mm": 2000}),
            # 沒標籤的數字要用 x 串起來才算尺寸；色號、型號不是
            ("Natural Oak 天然橡木 / Cabanon Soft FCL7029-04 復古綠", {}),
            ("2 Seater / Heritage 18011 / Olive Green Lacquered", {}),
            ("深色橡木 / PC0 皮革・Sierra 1611", {}),
            ("Ariette 1 (80x80 cm)", {"width_mm": 800, "depth_mm": 800}),
            # --- 標籤和數字個數對不上：不猜（Codex 審查 2026-11-20）
            ("寬 × 高 × 深：285 × 307 mm", {}),
            # --- 色溫、瓦數、燈座、型號裡的字母都不是尺寸（居雅堂的規格名）
            ("Brown Opal / High Lustre Chrome / LED 27K", {}),  # LED 的 D 不是「深」
            ("LED D2W / Brass PVD", {}),
            ("230 / 3000K / Matt Black / Dimmer on Board", {}),
            ("燈泡規格：E27 40W", {}),
            ("180W x 90D x 75H cm", {"width_mm": 1800, "depth_mm": 900, "height_mm": 750}),
            # --- 「約」夾在標籤和數字中間
            ("圖示整高約390 cm，底座直徑47 cm", {"height_mm": 3900, "diameter_mm": 470}),
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

    @pytest.mark.parametrize(
        "raw, want",
        [
            # 真實資料：居雅堂、Sheeper 的 product_type 是中英黏在一起
            ("吊燈 Pendant", ("lighting", "pendant")),
            ("吊燈 Pendant Lamp", ("lighting", "pendant")),
            ("椅子 Accent Chair", ("furniture", "chair")),
            ("Accent Chair單椅", ("furniture", "chair")),
        ],
    )
    def test_chinese_and_english_glued_together_try_each_half(self, raw, want):
        assert nz.map_category(raw, self.MAPPING) == want

    @pytest.mark.parametrize("raw", ["吊燈(大)", "吊燈（大）", "吊燈 (中)"])
    def test_a_note_in_brackets_is_ignored(self, raw):
        # 真實資料：NOSA 寫「吧檯椅(中)」「吧檯椅(高)」
        assert nz.map_category(raw, self.MAPPING) == ("lighting", "pendant")

    def test_a_broad_name_gives_only_the_big_category(self):
        # 真實資料：NOSA 所有的燈都寫「燈具」，分不出吊燈還是壁燈
        assert nz.map_category("燈具", {"燈具": ("lighting",)}) == ("lighting", None)

    def test_a_specific_match_beats_a_broad_one(self):
        # 「Light燈飾 Pendant」：燈飾只說是燈，Pendant 說是吊燈 —— 要吊燈
        mapping = {"燈飾": ("lighting",), "pendant": ("lighting", "pendant")}
        assert nz.map_category("Light燈飾 Pendant", mapping) == ("lighting", "pendant")

    def test_unmapped_returns_none_so_you_can_find_the_gaps(self):
        # 回 None 而不是猜，這樣才查得出「還有哪些分類沒對應」
        assert nz.map_category("按摩椅", self.MAPPING) == (None, None)

    def test_empty_returns_none(self):
        assert nz.map_category("", self.MAPPING) == (None, None)


class TestSubcategoryFromTitle:
    """網站分類太粗（只寫「燈具」）時，從標題找小分類。只在同一個大分類裡找。"""

    MAPPING: ClassVar[dict] = {
        "吊燈": ("lighting", "pendant"),
        "壁燈": ("lighting", "wall"),
        "吸頂燈": ("lighting", "ceiling"),
        "pendant lamp": ("lighting", "pendant"),
        "bulb": ("lighting", "bulb"),
        "掛飾": ("decor", "wall_decor"),
        "pot": ("greenery", "planter"),
    }

    @pytest.mark.parametrize(
        "title, want",
        [
            # 真實標題（NOSA）
            ("Ingo Maurer - Zettel'z 6 吊燈", "pendant"),
            # 標題是「品名在前、類別詞在後」，所以取最後出現的那個
            ("Ingo Maurer - 18x18 壁燈／吸頂燈", "ceiling"),
            ("Audo Copenhagen - TR Bulb 吊燈", "pendant"),  # 'Bulb' 是品名，不是燈泡
            ("Audo TR Bulb Pendant Lamp", "pendant"),
        ],
    )
    def test_finds_the_type_word_in_the_title(self, title, want):
        assert nz.subcategory_from_title(title, "lighting", self.MAPPING) == want

    def test_stays_inside_the_big_category(self):
        # 家飾的標題裡出現「吊燈」，也不能變成燈
        assert nz.subcategory_from_title("吊燈造型掛飾", "decor", self.MAPPING) == "wall_decor"
        assert nz.subcategory_from_title("吊燈造型擺件", "decor", self.MAPPING) is None

    def test_english_words_must_be_whole_words(self):
        # 'pot' 不能從 'Teapot' 裡面找到
        assert nz.subcategory_from_title("Teapot", "greenery", self.MAPPING) is None
        assert nz.subcategory_from_title("Clay Pot 30", "greenery", self.MAPPING) == "planter"

    @pytest.mark.parametrize("title", ["", None, "Zettel'z 6"])
    def test_nothing_found_returns_none(self, title):
        assert nz.subcategory_from_title(title, "lighting", self.MAPPING) is None


class TestCategoryFromTitle:
    """網站完全沒給分類（Shopline）時，從標題找最後一個類別詞，哪個大分類都可以。"""

    MAPPING: ClassVar[dict] = {"邊桌": ("furniture", "table"), "吊燈": ("lighting", "pendant")}

    def test_finds_a_type_word_inside_a_longer_word(self):
        assert nz.category_from_title("無名小廠 方形邊桌", self.MAPPING) == ("furniture", "table")

    def test_the_last_type_word_wins(self):
        assert nz.category_from_title("吊燈造型邊桌", self.MAPPING) == ("furniture", "table")

    @pytest.mark.parametrize("title", ["", None, "神秘的東西"])
    def test_nothing_found(self, title):
        assert nz.category_from_title(title, self.MAPPING) == (None, None)


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
