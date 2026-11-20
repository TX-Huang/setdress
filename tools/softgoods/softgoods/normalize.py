"""正規化：把 30 種寫法變成 1 種。

這是整個專案最容易出錯、也最值得測試的一層。
每個函式都是純函式（吃字串、吐值、不碰網路也不碰資料庫），所以測起來很快。

錢和尺寸都用 Decimal 算再轉整數。float 會給你 125.49999999999999。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal

# 全形轉半形，順便把各種乘號統一成 x
_FW = str.maketrans(
    {
        "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
        "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
        "．": ".", "ｘ": "x", "Ｘ": "x", "×": "x", "╳": "x", "✕": "x", "✖": "x",
        "－": "-", "～": "~", "，": ",", "、": ",", "　": " ",
        "（": "(", "）": ")", "［": "[", "］": "]",
    }
)


def _half(s) -> str:
    return str(s).translate(_FW) if s else ""


def slug(s) -> str:
    """做 id 用。英數轉小寫連字號，中文原樣保留。"""
    out = re.sub(r"[^0-9a-zA-Z一-鿿]+", "-", str(s or "").strip().lower())
    return out.strip("-") or "unknown"


# ===================================================== 尺寸 → mm

# 單位換成 mm 的倍率。長的要排在短的前面（mm 要比 m 先比對到）
_UNIT_MM = {
    "mm": "1", "公厘": "1", "毫米": "1",
    "cm": "10", "公分": "10", "厘米": "10", "cms": "10",
    "m": "1000", "公尺": "1000", "米": "1000",
    "ft": "304.8", "feet": "304.8", "呎": "304.8",
    "inch": "25.4", "inches": "25.4", "in": "25.4", "吋": "25.4", '"': "25.4",
    "台尺": "303",
}
_UNIT_RE = "|".join(sorted((re.escape(u) for u in _UNIT_MM), key=len, reverse=True))

# 標籤 → 欄位。一樣長的排前面；單字母 W/D/H/L 放最後，免得吃掉中文詞
_LABEL_FIELDS: list[tuple[str, str]] = [
    (r"圓直徑|直徑|口徑|外徑|徑|diameter|dia\.?|Ø|ø|⌀|∅|φ", "diameter_mm"),
    (r"寬度|寬|長度|長|width|length", "width_mm"),
    (r"深度|深|厚度|厚|depth", "depth_mm"),
    (r"高度|高|height", "height_mm"),
    # 前面不能接英文字母（乘號 x 除外）：「LED」的 D 不是「深」
    (r"(?<![A-WYZa-wyz])(?:W|L)", "width_mm"),
    (r"(?<![A-WYZa-wyz])D", "depth_mm"),
    (r"(?<![A-WYZa-wyz])H", "height_mm"),
]
_LABEL_RE = "|".join(p for p, _ in _LABEL_FIELDS)

_TOKEN_RE = re.compile(
    rf"(?P<pre>{_LABEL_RE})?\s*(?:約\s*)?"  # 「整高約 390 cm」
    rf"(?P<num>\d+(?:\.\d+)?)\s*"
    rf"(?P<unit>(?:{_UNIT_RE})(?![A-Za-z]))?\s*"  # 「200 min」的 m 不是公尺
    # 後置標籤後面不能緊接數字：「W1000 D600」的 D 是 600 的，不是 1000 的
    rf"(?P<post>(?:{_LABEL_RE})(?!\s*\d))?",
    re.IGNORECASE,
)

# 配件的長度不是商品尺寸。
# 「桌燈 · Ø28 x 高 42.5 cm，電線長 200 cm」的 200 cm 是電線，不是桌燈寬 2 公尺。
# 這是跑真實資料才發現的 —— 因為「長」也是寬度的標籤之一。
_ACCESSORY_LEN = re.compile(
    rf"(?:充電線|延長線|電線|吊線|吊繩|線|鍊|鏈|繩|帶)長度?\s*(?:約)?\s*"
    rf"\d+(?:\.\d+)?\s*(?:{_UNIT_RE})?",
    re.IGNORECASE,
)


def _field_for(label: str | None) -> str | None:
    if not label:
        return None
    for pattern, fieldname in _LABEL_FIELDS:
        if re.fullmatch(pattern, label, re.IGNORECASE):
            return fieldname
    return None


def _to_mm(num: str, unit: str | None, fallback: str) -> int:
    scale = _UNIT_MM.get((unit or "").lower(), fallback)
    mm = Decimal(num) * Decimal(scale)
    return int(mm.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _tokenize(text: str) -> list[tuple[str | None, str, str | None]]:
    """抓出所有 (標籤, 數字, 單位)。標籤可能在數字前面或後面。"""
    found = []
    for m in _TOKEN_RE.finditer(text):
        label = m.group("pre") or m.group("post")
        found.append((label, m.group("num"), m.group("unit")))
    return found


_MM_GUESS = Decimal(400)


def _fallback_scale(tokens: list[tuple[str | None, str, str | None]]) -> str:
    """沒寫單位的數字用什麼單位。

    整串只出現一種單位 → 跟著它。完全沒寫單位 → 最大的數字 ≥ 400 當 mm
    （Sheeper「W 1,200 × D 600 × H 320」都是 mm；4 m 以上的軟裝很少見），不然當公分（床墊「180x200」）。
    單位混著用 → 公分。
    """
    units = {u.lower() for _, _, u in tokens if u}
    if len(units) == 1:
        return _UNIT_MM[units.pop()]
    return _guess_unitless(tokens) if not units else "10"


def _guess_unitless(tokens: list[tuple[str | None, str, str | None]]) -> str:
    biggest = max((Decimal(n) for _, n, _ in tokens), default=Decimal(0))
    return "1" if biggest >= _MM_GUESS else "10"


def _long_and_wide(tokens) -> bool:
    """「長」和「寬」都寫了（「長 × 寬 × 高：130 × 120 × 73」）。"""
    words = {(label or "")[:1] for label, _, _ in tokens}
    return {"長", "寬"} <= words


def _dims_from_labels(tokens, fallback: str) -> dict[str, int]:
    """看得到標籤（寬/高/Ø/W/D/H）就只採信標籤。

    長和寬都寫了：長是寬（長邊），寬是深。不然兩個都算寬，深就不見了。
    """
    out: dict[str, int] = {}
    swap = _long_and_wide(tokens)
    for label, num, unit in tokens:
        fieldname = "depth_mm" if swap and (label or "").startswith("寬") else _field_for(label)
        if fieldname:
            out.setdefault(fieldname, _to_mm(num, unit, fallback))
    return out


# 完全沒標籤時的順序：兩個數字 = 寬 x 深（地毯那種攤平的），三個 = 寬 x 深 x 高
_BARE_ORDER = ("width_mm", "depth_mm", "height_mm")


def _dims_from_position(tokens, fallback: str) -> dict[str, int]:
    bare = [(n, u) for _, n, u in tokens]
    if len(bare) not in (2, 3):
        return {}  # 一個數字太曖昧，寧可不猜
    return {_BARE_ORDER[i]: _to_mm(n, u, fallback) for i, (n, u) in enumerate(bare)}


# 標籤全寫在前面、數字全寫在後面：「寬 × 高 × 深：285 × 307 × 285 mm」（居雅堂）
_HEADER_WORD = r"出牆深度|寬度|寬|長度|長|深度|深|高度|高|直徑|W|D|H|L"
_TIMES = r"\s*[x*]\s*"
_NUM = r"\d+(?:\.\d+)?"
_HEADER_RE = re.compile(
    rf"(?P<labels>(?:{_HEADER_WORD})(?:{_TIMES}(?:{_HEADER_WORD}))+)\s*[:：]?\s*"
    rf"(?P<nums>{_NUM}(?:{_TIMES}{_NUM})+)",
    re.IGNORECASE,
)


def _pair_header(m: re.Match) -> str:
    labels = re.split(_TIMES, m.group("labels"), flags=re.IGNORECASE)
    nums = re.split(_TIMES, m.group("nums"), flags=re.IGNORECASE)
    if len(labels) != len(nums):
        return " "  # 標籤和數字個數對不上，哪個是哪個說不準 —— 整段不採用，不要照位置猜
    return " x ".join(f"{lab} {num}" for lab, num in zip(labels, nums, strict=True))


# 不是尺寸的數字，先拿掉：
#   電壓「110-240V」原本被當成寬 110 cm、深 240 cm
#   色溫「3000K」、燈座「E27」
#   瓦數「40W」（但「180W x 90D」的 W 是寬，後面接著 x 的不拿）
_END = r"(?![A-Za-z0-9])"  # 不用 \b：「110-240V電壓」的 V 後面直接接中文，\b 會失效
_NOT_A_SIZE = re.compile(
    r"(?<![\d\s.])x\d+|"  # 數量「箱型×1」「鋼板x1」（乘號直接黏在字後面、數字前面）
    rf"{_NUM}(?:\s*[-/~]\s*{_NUM})*\s*[Vv]{_END}"
    rf"|{_NUM}\s*[Kk]{_END}"
    rf"|(?<![A-Za-z])E\d\d{_END}"
    rf"|{_NUM}\s*W{_END}(?!\s*[x*])"
)
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")  # 「1,200」→「1200」
# 沒標籤的數字要用 x 串起來才算尺寸：「180x200」「200 x 300 cm」。色號「RAL 6020」、型號「FCL7029-04」不算
_CHAIN = re.compile(
    rf"{_NUM}\s*(?:{_UNIT_RE})?(?:\s*[x*]\s*{_NUM}\s*(?:{_UNIT_RE})?)+", re.IGNORECASE
)


def _dims_without_labels(text: str) -> dict[str, int]:
    chain = _CHAIN.search(text)
    if not chain:
        return {}
    bare = _tokenize(chain.group())
    return _dims_from_position(bare, _fallback_scale(bare))


def parse_dimensions(raw) -> dict[str, int]:
    """尺寸字串 → {width_mm, depth_mm, height_mm, diameter_mm}，單位一律 mm。"""
    text = _ACCESSORY_LEN.sub(" ", _half(raw))  # 先把電線長那種配件長度剔掉
    text = _THOUSANDS.sub("", _NOT_A_SIZE.sub(" ", text))
    text = _HEADER_RE.sub(_pair_header, text)  # 「寬 × 高：30 × 40」→「寬 30 x 高 40」
    if not text or not re.search(r"\d", text):
        return {}

    labelled = [t for t in _tokenize(text) if _field_for(t[0])]
    if labelled:  # 看得到標籤（寬/高/Ø/W/D/H）就只採信標籤
        return _dims_from_labels(labelled, _fallback_scale(labelled))
    return _dims_without_labels(text)


# ======================================================== 價格

def parse_price(raw) -> int | None:
    """'NT$7,600 起' → 7600。錢一律整數，不要用 float。"""
    text = _half(raw).replace(",", "")
    m = re.search(r"\d+(?:\.\d+)?", text)
    if not m:
        return None
    return int(Decimal(m.group()).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ======================================================== 品牌

def brand_id(name, aliases: dict[str, list[str]] | None = None) -> str:
    """把同一個品牌的各種寫法收斂成一個 id。"""
    if not name or not str(name).strip():
        return "unknown"
    key = str(name).strip().casefold()
    for bid, spellings in (aliases or {}).items():
        if key == bid.casefold() or any(key == s.strip().casefold() for s in spellings):
            return bid
    return slug(name)


# ======================================================== 分類

_CAT_SEPARATORS = re.compile(r"[/／、,|｜>＞]")
_BRACKET_NOTE = re.compile(r"\s*[(（][^)）]*[)）]")  # 「吧檯椅(高)」的「(高)」
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")  # 「吊燈 Pendant」的「吊燈」
_LATIN_RUN = re.compile(r"[a-z](?:[a-z &'-]*[a-z])?", re.IGNORECASE)  # 「Light燈飾」的「Light」


def _category_candidates(text: str) -> Iterator[str]:
    """整串 → 斜線拆開的每一段；每一段再試「去掉括號註記」和「中英拆開」。"""
    for part in (text, *_CAT_SEPARATORS.split(text)):
        bare = _BRACKET_NOTE.sub("", part)
        yield part
        yield bare
        yield from _CJK_RUN.findall(bare)
        yield from _LATIN_RUN.findall(bare)


def _lookup_category(key: str, mapping: dict) -> tuple[str, str | None] | None:
    needle = key.strip().casefold()
    if not needle:
        return None
    for name, value in mapping.items():
        if str(name).strip().casefold() == needle:
            return (value[0], value[1] if len(value) > 1 else None)
    return None


def map_category(raw, mapping: dict) -> tuple[str | None, str | None]:
    """網站的分類名 → 我們的 (cat1, cat2)。

    整串先試一次，對不到再把斜線拆開一段一段試 ——
    真實資料常寫成「擺飾 / 雕塑 / 壁飾」這種多重分類。

    還是對不到就回 (None, None)，不要猜。
    這樣你才查得出「還有哪些分類沒對應」，去 category_map.yaml 補。
    """
    text = str(raw or "").strip()
    hits = [h for c in _category_candidates(text) if (h := _lookup_category(c, mapping))]
    return _most_specific(hits)


def _most_specific(hits: list[tuple[str, str | None]]) -> tuple[str | None, str | None]:
    """有小分類的優先：「Light燈飾 Pendant」要吊燈，不要只是「燈」。都沒有回 (None, None)。"""
    specific = [h for h in hits if h[1]]
    return (specific or hits or [(None, None)])[0]


def _last_position(text: str, word: str) -> int | None:
    """word 在 text 裡最後一次出現的結尾位置。英文要整個字對到（'pot' 不能從 'Teapot' 找到）。"""
    if not word.isascii():
        start = text.rfind(word)
        return start + len(word) if start >= 0 else None
    hits = list(re.finditer(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text))
    return hits[-1].end() if hits else None


def _usable_entry(value, cat1: str | None) -> bool:
    """有小分類的那幾筆；指定了大分類就只要那一類的。"""
    has_sub = len(value) > 1 and bool(value[1])
    return has_sub and (not cat1 or value[0] == cat1)


def _title_hits(text: str, mapping: dict, cat1: str | None) -> Iterator[tuple[int, int, str, str]]:
    """標題裡出現的類別詞：(結尾位置, 長度, 大分類, 小分類)。cat1 是 None 就不限大分類。"""
    for name, value in mapping.items():
        if not _usable_entry(value, cat1):
            continue
        word = str(name).strip().casefold()
        end = _last_position(text, word)
        if end is not None:
            yield (end, len(word), value[0], value[1])


def _last_title_hit(title, mapping: dict, cat1: str | None) -> tuple[int, int, str, str] | None:
    """標題是「品名在前、類別詞在後」（「Audo TR Bulb 吊燈」的 Bulb 是品名），所以取最後出現的。"""
    return max(_title_hits(str(title).casefold(), mapping, cat1), default=None) if title else None


def subcategory_from_title(title, cat1: str, mapping: dict) -> str | None:
    """網站分類太粗（NOSA 的燈全寫「燈具」）時，從標題找小分類。只在同一個大分類裡找。找不到回 None。"""
    best = _last_title_hit(title, mapping, cat1)
    return best[3] if best else None


def category_from_title(title, mapping: dict) -> tuple[str | None, str | None]:
    """網站完全沒給分類（Shopline）時，從標題找最後一個類別詞：「方形邊桌」→ 家具／桌。"""
    best = _last_title_hit(title, mapping, None)
    return (best[2], best[3]) if best else (None, None)


# ======================================================== 庫存 / 交期

_LEAD_UNIT_DAYS = {"工作日": 1, "月": 30, "週": 7, "周": 7, "星期": 7, "天": 1, "日": 1}
_LEAD_RE = re.compile(
    r"(\d+)\s*(?:[-~]|到|至)?\s*(?:\d+)?\s*個?\s*(工作日|月|週|周|星期|天|日)"
)


def parse_lead_time(raw) -> int | None:
    """'預購 6 - 8 個月' → 180 天。

    回「最快多久」（下界）。想知道最慢，去看 listing.stock_text 原文。
    """
    text = _half(raw)
    if not text:
        return None
    m = _LEAD_RE.search(text)
    if m:
        return int(m.group(1)) * _LEAD_UNIT_DAYS[m.group(2)]
    return 0 if "現貨" in text else None


_CN_NUM = {"一": 1, "二": 2, "兩": 2, "雙": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
# 只認「盞/件/入/顆/支」這些真正數東西的單位
_PACK_CN = re.compile(rf"(\d+|[{''.join(_CN_NUM)}])\s*(?:盞|件|入|顆|支)")
_PACK_EN = re.compile(r"set\s+of\s+(\d+)|(\d+)\s*(?:pcs|pieces|pack)", re.IGNORECASE)


def pack_size(raw) -> int:
    """'三盞吊燈組' → 3。單品回 1。

    為什麼需要這個：多盞組的尺寸標示跟單盞一樣（都寫 Ø20 x H22），
    所以不看組數就會把 167,000 的五盞組跟 31,100 的單盞放在一起比價。

    注意「三節閱讀立燈」是三節燈臂、「雙頭款吊燈」是一盞兩頭 —— 都回 1。
    所以只認 盞/件/入/顆/支，不認 節/頭。
    """
    text = _half(raw)
    if not text:
        return 1
    m = _PACK_EN.search(text)
    if m:
        return int(m.group(1) or m.group(2))
    m = _PACK_CN.search(text)
    if m:
        token = m.group(1)
        return int(token) if token.isdigit() else _CN_NUM[token]
    return 1


def in_stock(raw) -> bool | None:
    """只有真的有貨才算 True。

    「可下單」不是現貨 —— 這個差別對買家最重要，不要混在一起。
    """
    if not raw or not str(raw).strip():
        return None
    text = str(raw)
    return any(w in text for w in ("現貨", "有庫存", "立即出貨", "當日出貨"))


# ======================================================== 顏色

# 順序有意義：先比金屬色，否則「黃銅」會被「黃」抓去當黃色
_COLOR_FAMILIES: list[tuple[str, tuple[str, ...]]] = [
    ("metallic", ("紅銅", "黃銅", "青銅", "古銅", "銅", "鍍鉻", "鍍金", "鍍鎳", "不鏽鋼",
                  "金色", "銀色", "香檳金", "玫瑰金", "brass", "copper", "bronze",
                  "chrome", "nickel", "gold", "silver", "steel", "aluminium")),
    ("black", ("黑", "black", "墨")),
    ("white", ("白", "象牙", "white", "ivory", "cream")),
    ("grey", ("灰", "grey", "gray", "石墨")),
    ("brown", ("棕", "咖啡", "褐", "胡桃", "brown", "walnut", "coffee")),
    ("beige", ("卡其", "燕麥", "亞麻色", "beige", "oat", "sand", "taupe")),
    ("red", ("紅", "酒紅", "磚", "red", "burgundy", "terracotta")),
    ("orange", ("橘", "橙", "orange")),
    ("yellow", ("黃", "芥末", "yellow", "mustard")),
    ("green", ("綠", "橄欖", "墨綠", "green", "olive", "sage")),
    ("blue", ("藍", "靛", "blue", "navy", "teal")),
    ("purple", ("紫", "purple", "lilac")),
    ("pink", ("粉", "pink", "blush")),
    ("clear", ("透明", "clear", "transparent", "crystal")),
    ("wood", ("原木", "橡木", "柚木", "木紋", "oak", "teak", "ash", "wood")),
]


def color_family(raw) -> str | None:
    """'紅銅' → 'metallic'。認不出來就回 None，不要瞎猜。"""
    if not raw or not str(raw).strip():
        return None
    text = str(raw).casefold()
    for family, words in _COLOR_FAMILIES:
        if any(w.casefold() in text for w in words):
            return family
    return None


# ======================================================== 標題清理

# 促銷用的框框，整塊丟掉
_PROMO_BLOCK = re.compile(r"[【\[(（][^】\])）]{0,20}(?:出清|預購|現貨|限時|免運|特價|新品|熱銷|優惠|下殺)[^】\])）]{0,20}[】\])）]")
_BRACKET_BLOCK = re.compile(r"【[^】]*】|\[[^\]]*\]")
_TRAIL_PAREN = re.compile(r"[(（]([^)）]{1,20})[)）]\s*$")

# 只在「結尾」才拿掉的詞。放中間不動 ——
# Tom Dixon 真的有一款叫 "Beat Light Fat"，把中間的 Light 砍掉就毀了。
_TRAILING_NOISE = (
    "無線桌燈", "行動桌燈", "可攜式", "充電式", "無線", "桌上燈",
    "吊燈", "吸頂燈", "半吸頂", "壁燈", "桌燈", "檯燈", "立燈", "落地燈",
    "軌道燈", "嵌燈", "筒燈", "夜燈", "燈具", "壁掛燈", "頂燈",
    "沙發", "單椅", "餐椅", "休閒椅", "吧檯椅", "長凳", "腳凳",
    "餐桌", "茶几", "邊桌", "書桌", "斗櫃", "書櫃", "層架",
    "地毯", "地墊", "抱枕", "靠墊", "窗簾", "蓋毯", "床包", "被套",
    "花器", "花瓶", "鏡子", "掛鏡", "托盤", "掛鐘", "擺件",
    "系列", "正品", "公司貨", "原裝", "進口",
)
_TRAILING_SORTED = sorted(_TRAILING_NOISE, key=len, reverse=True)
_SEPARATORS = " \t·‧•-–—/／,，|"  # 「吸頂燈／壁燈」的全形斜線也算


def _strip_trailing_noise(s: str) -> str:
    """從結尾一層一層剝掉分類詞和雜訊詞，剝不動了才停。"""
    changed = True
    while changed:
        changed = False
        s = s.strip(_SEPARATORS)
        for word in _TRAILING_SORTED:
            if s.casefold().endswith(word.casefold()) and len(s) > len(word):
                s = s[: -len(word)]
                changed = True
                break
    return s.strip(_SEPARATORS)


def clean_title(title, brand=None) -> tuple[str, str | None]:
    """通路標題 → (型號, 顏色)。

    '【 展示品出清 】Tom Dixon Puff 吊燈 (黃銅)' → ('Puff', '黃銅')

    挖得出型號，才有辦法比對「兩個站是不是同一款商品」。
    """
    original = str(title or "").strip()
    if not original:
        return ("", None)

    s = _half(original)

    # 1. 結尾括號 → 可能是顏色
    color = None
    m = _TRAIL_PAREN.search(s)
    if m:
        inner = m.group(1).strip()
        if color_family(inner):
            color = inner
        s = s[: m.start()]

    # 2. 促銷框框整塊丟掉
    s = _PROMO_BLOCK.sub(" ", s)
    s = _BRACKET_BLOCK.sub(" ", s)

    # 3. 品牌名拿掉
    if brand:
        s = re.sub(re.escape(str(brand)), " ", s, flags=re.IGNORECASE)

    # 4. 結尾的分類詞剝掉
    s = _strip_trailing_noise(s)
    s = re.sub(r"\s{2,}", " ", s).strip(_SEPARATORS)

    return (s or original, color)
