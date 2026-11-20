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
