"""抓取層：全部的網站共用這一份。

它只做四件事，但這四件事是爬蟲會不會惹人討厭的全部：
  1. 快取 —— 抓過的絕不重抓。你改 parse 一百次，網站只被打一次。
  2. robots —— 禁止的網址「打之前」就拒絕，不是抓了才檢查。
  3. 限速 —— 每個站各自的延遲；站方自己寫了更慢的 Crawl-delay 就聽它的。
  4. 重試 —— 連線失敗退讓重試；404 不重試（重幾次都一樣，純粹浪費別人的機器）。

真正的網路呼叫是注入的（transport），所以測試可以完全離線跑，
而且可以驗證「到底打了幾次請求」—— 那才是爬蟲最該測的事。
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import time
from collections.abc import Callable
from urllib.robotparser import RobotFileParser

import requests

from .models import SiteConfig


class Blocked(Exception):
    """robots.txt 不給抓這個網址。"""


class FetchError(Exception):
    """重試完還是拿不到。"""


def _requests_transport(url: str, headers: dict, timeout: float) -> tuple[int, str]:
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.encoding = resp.encoding or "utf-8"
    return resp.status_code, resp.text


# 這些狀態碼重試有意義（對方暫時掛了或在限速）
_RETRYABLE = {408, 425, 429, 500, 502, 503, 504}

Transport = Callable[[str, dict, float], tuple[int, str]]


class Fetcher:
    def __init__(
        self,
        site: SiteConfig,
        cache_dir: pathlib.Path | str,
        transport: Transport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        max_retry: int = 3,
        timeout: float = 20.0,
    ):
        self.site = site
        # 每個站一個子資料夾：不同站可能有一樣的路徑，快取不能撞在一起
        self.cache_dir = pathlib.Path(cache_dir) / site.site_id
        self.transport: Transport = transport or _requests_transport
        self.sleeper = sleeper
        self.max_retry = max_retry
        self.timeout = timeout
        self.delay = site.crawl_delay_sec
        self.stats = {"downloaded": 0, "cached": 0, "failed": 0, "blocked": 0}
        self._robots: RobotFileParser | None = None
        self._robots_loaded = False

    # ---------------------------------------------------------- 快取

    def cache_path(self, url: str) -> pathlib.Path:
        """網址 → 本地檔名。雜湊保證唯一，前面那段保留可讀性。"""
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        readable = re.sub(r"[^a-zA-Z0-9._-]+", "_", url.split("://", 1)[-1])[:60]
        return self.cache_dir / f"{readable}__{digest}.txt"

    # --------------------------------------------------------- robots

    def _load_robots(self) -> None:
        """robots.txt 只讀一次，放記憶體。"""
        self._robots_loaded = True
        url = f"{self.site.base_url}/robots.txt"
        try:
            status, body = self.transport(url, self._headers(), self.timeout)
        except requests.RequestException:
            return  # 讀不到就當沒有規則
        self.sleeper(self.delay)
        if status != 200 or not body.strip():
            return

        parser = RobotFileParser()
        parser.parse(body.splitlines())
        self._robots = parser

        # 站方自己要求更慢，就聽它的。更快我們不接受。
        asked = re.search(r"(?im)^\s*crawl-delay:\s*([\d.]+)", body)
        if asked:
            self.delay = max(self.delay, float(asked.group(1)))

    def allowed(self, url: str) -> bool:
        if not self.site.obey_robots:
            return True
        if not self._robots_loaded:
            self._load_robots()
        return self._robots is None or self._robots.can_fetch(self.site.user_agent, url)

    # ------------------------------------------------------- 下載

    def _headers(self) -> dict:
        return {
            "User-Agent": self.site.user_agent,
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        }

    def _download(self, url: str) -> str:
        last = ""
        for attempt in range(1, self.max_retry + 1):
            try:
                status, body = self.transport(url, self._headers(), self.timeout)
            except requests.RequestException as e:
                last = f"{type(e).__name__}: {e}"
            else:
                if status == 200:
                    return body
                last = f"HTTP {status}"
                if status not in _RETRYABLE:
                    break  # 404 這種重試沒意義
            if attempt < self.max_retry:
                self.sleeper(self.delay * attempt * 2)  # 退讓：每次等更久

        self.stats["failed"] += 1
        self.sleeper(self.delay)  # 失敗也要等，不然一連串 404 會連珠炮打過去
        raise FetchError(f"抓取失敗（{last}）: {url}")

    # --------------------------------------------------------- 主要入口

    def __call__(self, url: str, trim: Callable[[str], str] | None = None) -> str:
        """抓一個網址。順序是：快取 → robots → 下載 → 等待。

        trim：存快取前先瘦身（整頁商品頁 0.7 MB，只要看得到的文字）。快取裡存的是瘦身後的。
        """
        path = self.cache_path(url)
        if path.exists():
            self.stats["cached"] += 1
            return path.read_text(encoding="utf-8")

        if not self.allowed(url):
            self.stats["blocked"] += 1
            raise Blocked(f"robots.txt 不允許: {url}")

        body = self._download(url)
        if trim:
            body = trim(body)

        # 成功才寫快取。失敗寫進去，下次重跑會永遠拿到空的。
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        self.stats["downloaded"] += 1

        self.sleeper(self.delay)
        return body
