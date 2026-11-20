"""從商品介紹文字找出「尺寸那一行」（規格：SIZES.md）。

只回那一行。介紹文字本身有著作權，不存（policy.py）。

依序找：
  1. 有標籤的行：「尺寸：寬 19 x 深 28 x 高 28 cm」
  2. 標題行底下：「尺寸」單獨一行，下面幾行才是數字
  3. 都沒有：「寬12 cm × 深65 cm × 高65 cm｜材質…」這種帶兩個以上標籤的片段
找不到回 None，不要猜。
"""

from __future__ import annotations

import html
import re
from itertools import takewhile

from . import normalize as nz

MAX_LEN = 120  # 比這長的是一段介紹，不是尺寸
HEADING_SPAN = 6  # 標題行底下最多看幾行（NOSA 的尺寸表一個欄位一行）

_NOT_TEXT = re.compile(r"<(script|style|svg|noscript|template)\b.*?</\1\s*>|<!--.*?-->", re.IGNORECASE | re.DOTALL)
_ATTRS = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>")
_BREAK = re.compile(r"<(?:br|/p|/li|/div|/h\d|/tr)\b[^>]*>", re.IGNORECASE)
_CELL = re.compile(r"</t[dh]>", re.IGNORECASE)  # 表格同一列的格子留在同一行：「寬」「25 cm」
_TAG = re.compile(r"<[^>]+>")
_NOTE = re.compile(r"\s*[(（][^)）\d]*[)）]")  # 沒有數字的括號註記：「（燈臂可調）」

_NAME = r"(?:產品|商品)?(?:尺寸|dimensions?|size)(?:\s*(?:size|dimensions?))?"
_LABELLED = re.compile(rf"^{_NAME}\s*[:：]\s*(?P<rest>.+)$", re.IGNORECASE)
_HEADING = re.compile(rf"^{_NAME}\s*[:：]?$", re.IGNORECASE)

# 整句都不要：電線截面積「2 x 0.75 mm²」
_CROSS_SECTION = re.compile(r"mm²|mm2\b|平方")
# 尺寸那一段裡出現就不要：範圍（30-50、148 到 175）、可調、瓦數 40W、色溫 3000K、燈座 E27
_NOT_SIZE = re.compile(
    r"可調|調整|延伸|至|到|~|～|\d\s*[-–—]\s*\d"
    r"|\d\s*W(?![A-Za-z0-9])(?!\s*[x×*])|\d\s*[Kk](?![A-Za-z0-9])|(?<![A-Za-z])E\d\d(?![A-Za-z0-9])"
)
# 尺寸到最後一個「數字＋單位」為止，後面的介紹、瓦數、註記都切掉
_LAST_UNIT = re.compile(r"\d\s*(?:mm|cm|公分|公釐|公尺|inch|吋|ft|m)(?![A-Za-z])[)）]?", re.IGNORECASE)
_LEADING_WORDS = re.compile(r"^(?:[^\d，,；;｜|/／]*[，,；;｜|/／]\s*)+")  # 開頭沒有數字的句子
_PARTS = re.compile(r"[｜|/／;；，,]")  # 一行寫好幾件事時的分隔
_DIM_LABEL = re.compile(r"(?:寬|長|深|高|直徑|徑|[Øø⌀∅])\s*\d|(?<![A-Za-z])[WDHL]\s*\d")
_VARIANT_SPLIT = re.compile(r"[\s/|,，、]+")


def slim_html(page: str) -> str:
    """整頁商品頁（約 0.7 MB）→ 只留看得到的文字和標籤骨架（約 5%）。存快取前用。"""
    return " ".join(_ATTRS.sub(r"<\1>", _NOT_TEXT.sub("", page)).split())


def text_lines(body: str | None) -> list[str]:
    """HTML → 一行一行的純文字。段落、換行、清單項目、表格的一列都算一行。"""
    if not body:
        return []
    body = " ".join(_NOT_TEXT.sub("", body).split())  # 原始碼的換行只是空白，分行只看標籤
    text = html.unescape(_TAG.sub("", _CELL.sub(" ", _BREAK.sub("\n", body))))
    lines = (" ".join(ln.split()) for ln in text.splitlines())
    return [ln for ln in lines if ln]


def _cut_after_last_unit(text: str) -> str:
    ends = [m.end() for m in _LAST_UNIT.finditer(text)]
    return (text[: ends[-1]] if ends else text).strip()


def _size_span(text: str) -> str | None:
    """從頭切到最後一個「數字＋單位」；切出來是乾淨的尺寸就回它。"""
    if _CROSS_SECTION.search(text):
        return None
    span = _cut_after_last_unit(text)
    ok = 0 < len(span) <= MAX_LEN and not _NOT_SIZE.search(span) and nz.parse_dimensions(span)
    return span if ok else None


def _usable(text: str) -> str | None:
    """整段是尺寸就回整段；不是的話，看第一件事（「燈體：30 × 30 × 10 cm / 吸頂蓋：11 cm」）。

    括號註記、開頭沒有數字的句子先拿掉；最後一個單位後面的東西切掉。
    """
    text = _NOTE.sub("", text)
    if len(text) > MAX_LEN:
        return None  # 這麼長是一段介紹，不是尺寸
    text = _LEADING_WORDS.sub("", text)
    return _size_span(text) or _size_span(_PARTS.split(text, maxsplit=1)[0])


def _after_labels(lines: list[str]) -> list[str]:
    return [m.group("rest") for m in map(_LABELLED.match, lines) if m]


def _block_candidates(block: list[str]) -> list[str]:
    """標題底下的幾行：

    每一行自己就是完整尺寸（至少兩個方向）→ 多半是不同規格（「3X …」「4N …」），分開放，讓規格名去配；
    不然是同一個東西的幾個欄位（「寬 25 cm」「深 43.5 cm」），接成一段。
    """
    if len(block) > 1 and all(len(nz.parse_dimensions(b)) >= 2 for b in block):
        return block
    return ["，".join(block)] if block else []


def _under_headings(lines: list[str]) -> list[str]:
    out = []
    for i, line in enumerate(lines):
        if _HEADING.match(line):
            block = list(takewhile(bool, map(_usable, lines[i + 1 : i + 1 + HEADING_SPAN])))
            out.extend(_block_candidates(block))
    return out


def _labelled_segments(lines: list[str]) -> list[str]:
    segments = (s.strip() for line in lines for s in _PARTS.split(line))
    return [s for s in segments if len(_DIM_LABEL.findall(s)) >= 2]


def _variant_words(variant_name: str | None) -> list[str]:
    """一個字母的不要（S / M / L 太容易配錯，見 SIZES.md「不做的」）。"""
    return [w for w in _VARIANT_SPLIT.split(variant_name or "") if len(w) >= 2]


def _mentions(text: str, word: str) -> bool:
    """整個字對到才算：「N」不能從「4N」裡找到。"""
    pattern = rf"(?<![0-9A-Za-z]){re.escape(word)}(?![0-9A-Za-z])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def title_size(title: str | None) -> str | None:
    """標題裡有帶標籤和單位的尺寸（「Lantern 桌燈 (Ø40 cm)」）就回標題。

    「PH 3/2」（型號）、「沙發套 305cm」（沒說是哪個方向）不算。
    """
    has_size = bool(title) and _LAST_UNIT.search(title) and _DIM_LABEL.search(title)
    has_size = has_size and nz.parse_dimensions(title)
    return title if has_size else None


def _fits(candidate: str, want: dict[str, int]) -> bool:
    got = nz.parse_dimensions(candidate)
    shared = [k for k in want if k in got]
    return bool(shared) and all(abs(got[k] - want[k]) <= 5 for k in shared)


def _by_variant_word(found: list[str], variant_name: str | None) -> str | None:
    return next((s for w in _variant_words(variant_name) for s in found if _mentions(s, w)), None)


def _by_title(found: list[str], title: str | None) -> str | None:
    want = nz.parse_dimensions(title_size(title))
    return next((s for s in found if _fits(s, want)), None) if want else None


def _pick(found: list[str], variant_name: str | None, title: str | None) -> str:
    """好幾個尺寸時：先挑提到規格名（3X、4N）的；再挑跟標題尺寸對得上的（Lantern 小中大三頁）；都沒有拿第一個。"""
    return _by_variant_word(found, variant_name) or _by_title(found, title) or found[0]


def size_snippet(
    body: str | None, variant_name: str | None = None, title: str | None = None
) -> str | None:
    """介紹文字（HTML）→ 尺寸那一段。找不到回 None。規格名和標題用來從好幾個尺寸裡挑一個。"""
    lines = text_lines(body)
    for finder in (_after_labels, _under_headings, _labelled_segments):
        found = [s for s in map(_usable, finder(lines)) if s]
        if found:
            return _pick(found, variant_name, title)
    return None
