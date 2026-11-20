"""Adapter 的介面。

加一個新網站 = 寫一個新 adapter，只要實作兩個方法：

    discover(fetch) -> 產生要抓的網址
    parse(url, body) -> 把內容變成一串 Record

其他的（快取、限速、robots、寫資料庫、正規化）全部已經有了，不用再碰。
這就是「多站架構」的意思：共用的部分只有一份。
"""

from __future__ import annotations

import functools
import pathlib
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator

import yaml

from ..models import Record, SiteConfig

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

Fetch = Callable[..., str]  # fetch(url) 或 fetch(url, trim=...)：見 fetcher.Fetcher


@functools.cache
def _load_yaml(name: str) -> dict:
    path = DATA_DIR / name
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def default_category_map() -> dict:
    return _load_yaml("category_map.yaml")


def default_brand_aliases() -> dict:
    return _load_yaml("brands.yaml")


_LEADING_TAGS = re.compile(r"^\s*(?:【[^】]*】|\[[^\]]*\]|［[^］]*］)\s*")


def longest_first(names: list[str]) -> list[str]:
    """長的先比：「Louis Poulsen」勝過「Louis」。"""
    return sorted(names, key=len, reverse=True)


def brand_from_title(title: str, names: list[str]) -> str:
    """標題開頭是已知品牌就是它（names 要先 longest_first）。

    後面要接空白或符號，不能是字母：「Hayden」不是 HAY。開頭的【預購】這種框框先拿掉。
    """
    text = _LEADING_TAGS.sub("", title or "").casefold()
    for name in names:
        after = text[len(name) : len(name) + 1]
        if text.startswith(name.casefold()) and not after.isalnum():
            return name
    return ""


_BY_BRAND = re.compile(r"\s+by\s+(?P<brand>[^/|｜]+?)\s*$", re.IGNORECASE)


def split_by_brand(title: str, names: list[str]) -> tuple[str, str]:
    """標題最後寫「by 品牌」（Design Butik：「海芋 / 可攜式桌燈 by Ferm Living」）。

    回 (拿掉這段的標題, 品牌)；沒有就回 (原標題, "")。品牌在已知名單裡就用名單的寫法。
    「by」前後要有空白：「Standby」不算。
    """
    m = _BY_BRAND.search(title or "")
    if not m:
        return title, ""
    said = m.group("brand").strip()
    known = next((n for n in names if n.casefold() == said.casefold()), said)
    return title[: m.start()].rstrip(" -–—"), known


@functools.cache
def default_brand_names() -> list[str]:
    """已知的品牌名稱（data/known_brands.txt）。Shopline 沒有品牌欄位，用標題開頭比對。"""
    path = pathlib.Path(__file__).parent.parent / "data" / "known_brands.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


class Adapter(ABC):
    def __init__(
        self,
        site: SiteConfig,
        category_map: dict | None = None,
        brand_aliases: dict | None = None,
    ):
        self.site = site
        self.category_map = default_category_map() if category_map is None else category_map
        self.brand_aliases = default_brand_aliases() if brand_aliases is None else brand_aliases

    @abstractmethod
    def discover(self, fetch: Fetch) -> Iterator[str]:
        """產生這個站所有要抓的網址。

        允許自己呼叫 fetch（翻頁、讀 sitemap）。
        重複抓同一個網址不花成本 —— 第二次是走快取。
        """

    @abstractmethod
    def parse(self, url: str, body: str) -> list[Record]:
        """一個網址的內容 → 一串 Record。純函式，不要在這裡連網路。"""

    def crawl(self, fetch: Fetch) -> Iterator[Record]:
        for url in self.discover(fetch):
            yield from self.parse(url, fetch(url))
