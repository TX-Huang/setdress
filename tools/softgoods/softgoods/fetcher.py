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
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from .models import SiteConfig


class Blocked(Exception):
    """robots.txt 不給抓這個網址。"""


class FetchError(Exception):
    """重試完還是拿不到。"""


def _requests_transport(url: str, headers: dict, timeout: float) -> tuple[int, str]:
    """轉址不讓 requests 自己跟：Fetcher 要一跳一跳查 robots、等一下。轉址時 body 放 Location。"""
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)
    if resp.status_code in _REDIRECT:
        return resp.status_code, resp.headers.get("Location", "")
    resp.encoding = resp.encoding or "utf-8"
    return resp.status_code, resp.text


_REDIRECT = {301, 302, 303, 307, 308}
_DONE = {200} | _REDIRECT  # 這些不用重試
MAX_HOPS = 5


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
        fresh_since: float | None = None,
    ):
        self.site = site
        # 每個站一個子資料夾：不同站可能有一樣的路徑，快取不能撞在一起
        self.cache_dir = pathlib.Path(cache_dir) / site.site_id
        self.transport: Transport = transport or _requests_transport
        self.sleeper = sleeper
        self.max_retry = max_retry
        self.timeout = timeout
        # 定期更新用：這個時間以前存的快取不算數，重抓（這次跑的時候存的照樣用）。
        # None = 快取永遠有效 —— 改 parse 程式重跑時用，不打網站
        self.fresh_since = fresh_since
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
        parser.modified()  # 不設的話 crawl_delay() 會當成還沒讀過
        self._robots = parser

        # 站方自己要求更慢，就聽它的。更快我們不接受。
        # 只看寫給我們（或 *）的那一段：別的爬蟲的 Crawl-delay 不算（Codex 審查）
        asked = parser.crawl_delay(self.site.user_agent)
        if asked:
            self.delay = max(self.delay, float(asked))

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

    def _fail(self, message: str) -> FetchError:
        self.stats["failed"] += 1
        self.sleeper(self.delay)  # 失敗也要等，不然一連串 404 會連珠炮打過去
        return FetchError(message)

    def _try_once(self, url: str) -> tuple[int | None, str]:
        """打一次。連不上回 (None, 原因)。"""
        try:
            return self.transport(url, self._headers(), self.timeout)
        except requests.RequestException as e:
            return None, f"{type(e).__name__}: {e}"

    def _get_with_retry(self, url: str) -> tuple[int, str]:
        """打一個網址（不跟轉址）。200 或轉址就回；暫時性錯誤重試；其他丟 FetchError。"""
        last = ""
        for attempt in range(1, self.max_retry + 1):
            status, body = self._try_once(url)
            if status in _DONE:
                return status, body
            last = body if status is None else f"HTTP {status}"
            if status is not None and status not in _RETRYABLE:
                break  # 404 這種重試沒意義
            if attempt < self.max_retry:
                self.sleeper(self.delay * attempt * 2)  # 退讓：每次等更久
        raise self._fail(f"抓取失敗（{last}）: {url}")

    def _next_hop(self, url: str, location: str) -> str:
        """轉址的下一站：轉到別的網站不跟；robots 不給的不打（Codex 審查）。"""
        nxt = urljoin(url, location)
        if urlparse(nxt).netloc != urlparse(url).netloc:
            raise self._fail(f"轉到別的網站，不跟: {url} → {nxt}")
        if not self.allowed(nxt):
            self.stats["blocked"] += 1
            raise Blocked(f"轉址到 robots.txt 不允許的地方: {nxt}")
        return nxt

    def _download(self, url: str) -> str:
        """轉址自己一跳一跳跟：每一跳都查 robots、都等一下。"""
        for _ in range(MAX_HOPS):
            status, body = self._get_with_retry(url)
            if status not in _REDIRECT:
                return body
            url = self._next_hop(url, body)
            self.sleeper(self.delay)
        raise self._fail(f"轉址太多次: {url}")

    # --------------------------------------------------------- 主要入口

    def _usable_cache(self, path: pathlib.Path) -> bool:
        if not path.exists():
            return False
        return self.fresh_since is None or path.stat().st_mtime >= self.fresh_since

    def __call__(self, url: str, trim: Callable[[str], str] | None = None) -> str:
        """抓一個網址。順序是：快取 → robots → 下載 → 等待。

        trim：存快取前先瘦身（整頁商品頁 0.7 MB，只要看得到的文字）。快取裡存的是瘦身後的。
        """
        path = self.cache_path(url)
        if self._usable_cache(path):
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
